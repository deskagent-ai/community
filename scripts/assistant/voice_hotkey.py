# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
System-wide Voice Input Hotkey for DeskAgent.

Provides two modes:
1. Outlook Mode: Records voice → transcribes → starts reply_email agent automatically
2. Generic Mode: Records voice → transcribes → pastes text into active application

Architecture:
- Uses sounddevice for cross-platform audio recording
- Sends audio to local /transcribe endpoint (OpenAI Whisper)
- Detects active window to determine mode (Outlook vs generic)
- Integrates with keyboard library for system-wide hotkey
- Audio feedback beeps for start/stop recording
"""

import io
import sys
import time
import threading
import tempfile
from pathlib import Path

try:
    import sounddevice as sd
    import soundfile as sf
    import numpy as np
except (ImportError, OSError):
    # OSError: PortAudio library not found (Linux without audio)
    sd = None
    sf = None
    np = None

try:
    import requests
except ImportError:
    requests = None

try:
    import pyperclip
except ImportError:
    pyperclip = None

# Platform-specific imports
if sys.platform == 'win32':
    try:
        import win32gui
        import win32process
        import psutil
    except ImportError:
        win32gui = None
        win32process = None
        psutil = None

# Global handler reference for tray menu access
_voice_handler: 'VoiceHotkeyHandler | None' = None

# Module-level logging function
def _log(msg: str):
    """Log to system.log (works in background mode)."""
    try:
        import ai_agent
        ai_agent.system_log(msg)
    except ImportError:
        print(msg)  # Fallback for console mode


def _update_tray_status(status: str, task_name: str = None):
    """Update tray icon tooltip (safe import)."""
    try:
        from .core import update_tray_status
        update_tray_status(status, task_name)
    except ImportError:
        pass  # Ignore if not available


def _set_tray_idle():
    """Reset tray icon to idle state (safe import)."""
    try:
        from .core import set_tray_idle
        set_tray_idle()
    except ImportError:
        pass


def _set_recording_indicator(is_recording: bool):
    """Set visual recording indicator (cursor + tray icon)."""
    try:
        from .core import set_recording_cursor, set_tray_recording
        set_recording_cursor(is_recording)
        set_tray_recording(is_recording)
    except ImportError:
        pass
    except Exception as e:
        _log(f"[Voice] Error setting recording indicator: {e}")


def play_beep(frequency: int = 800, duration_ms: int = 150, volume: float = 0.3):
    """
    Play a short beep sound for audio feedback.

    Args:
        frequency: Tone frequency in Hz (default: 800)
        duration_ms: Duration in milliseconds (default: 150)
        volume: Volume level 0.0-1.0 (default: 0.3)
    """
    if not sd or not np:
        _log("[Voice] Beep skipped: sounddevice/numpy not available")
        return

    _log(f"[Voice] Playing beep: {frequency}Hz, {duration_ms}ms, volume={volume}")

    try:
        sample_rate = 44100
        duration = duration_ms / 1000.0

        # Log audio device info
        try:
            default_output = sd.query_devices(kind='output')
            _log(f"[Voice] Output device: {default_output['name']}")
        except Exception as e:
            _log(f"[Voice] Could not query output device: {e}")

        # Generate sine wave
        t = np.linspace(0, duration, int(sample_rate * duration), False)
        tone = np.sin(frequency * 2 * np.pi * t) * volume

        # Apply fade in/out to avoid clicks
        fade_samples = int(sample_rate * 0.01)  # 10ms fade
        fade_in = np.linspace(0, 1, fade_samples)
        fade_out = np.linspace(1, 0, fade_samples)
        tone[:fade_samples] *= fade_in
        tone[-fade_samples:] *= fade_out

        _log(f"[Voice] Calling sd.play() with {len(tone)} samples...")
        # Play the tone and wait for completion (blocking)
        sd.play(tone.astype(np.float32), sample_rate)
        _log(f"[Voice] Calling sd.wait()...")
        sd.wait()  # Wait for playback to complete
        _log(f"[Voice] Beep completed")
    except Exception as e:
        _log(f"[Voice] Beep error: {e}")
        import traceback
        _log(f"[Voice] Beep traceback: {traceback.format_exc()}")


class ProcessingSound:
    """Plays a soft pulsing sound while processing."""

    def __init__(self):
        self.playing = False
        self._thread = None

    def start(self):
        """Start playing processing sound in background."""
        if not sd or not np:
            return
        self.playing = True
        self._thread = threading.Thread(target=self._play_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop the processing sound."""
        self.playing = False

    def _play_loop(self):
        """Play soft ticks while processing."""
        sample_rate = 44100
        # Create a soft "tick" sound
        duration = 0.03  # 30ms
        t = np.linspace(0, duration, int(sample_rate * duration), False)
        # Soft click sound (short sine burst)
        tick = np.sin(600 * 2 * np.pi * t) * 0.08
        # Quick fade out
        fade = np.linspace(1, 0, len(tick))
        tick = tick * fade

        while self.playing:
            try:
                sd.play(tick, sample_rate)
                time.sleep(0.5)  # Tick every 500ms
            except Exception:
                break


class RecordingIndicatorSound:
    """Plays a very quiet ambient sound while recording to indicate active state."""

    def __init__(self, volume: float = 0.15, frequency: int = 200,
                 pulse_ms: int = 150, pause_ms: int = 800):
        """
        Initialize recording indicator sound.

        Args:
            volume: Volume level 0.0-1.0 (default: 0.15)
            frequency: Pulse frequency in Hz (default: 200)
            pulse_ms: Pulse duration in milliseconds (default: 150)
            pause_ms: Pause between pulses in milliseconds (default: 800)
        """
        self.playing = False
        self._thread = None
        self._stream = None
        self.volume = volume
        self.frequency = frequency
        self.pulse_ms = pulse_ms
        self.pause_ms = pause_ms

    def start(self):
        """Start playing indicator sound in background using separate output stream."""
        if not sd or not np:
            return
        self.playing = True
        self._thread = threading.Thread(target=self._play_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop the indicator sound."""
        self.playing = False
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    def _play_loop(self):
        """Play very quiet pulses while recording (uses output stream, not input)."""
        _log(f"[Voice] Indicator loop started: freq={self.frequency}Hz, volume={self.volume}, pulse={self.pulse_ms}ms, pause={self.pause_ms}ms")
        sample_rate = 44100
        # Use configurable pulse settings
        pulse_duration = self.pulse_ms / 1000.0  # Convert ms to seconds
        pause_duration = self.pause_ms / 1000.0  # Convert ms to seconds

        t = np.linspace(0, pulse_duration, int(sample_rate * pulse_duration), False)
        # Configurable frequency and volume
        pulse = np.sin(self.frequency * 2 * np.pi * t) * self.volume
        # Smooth fade in/out to avoid clicks
        fade_samples = int(sample_rate * 0.05)  # 50ms fade
        fade_in = np.linspace(0, 1, fade_samples)
        fade_out = np.linspace(1, 0, fade_samples)
        pulse[:fade_samples] *= fade_in
        pulse[-fade_samples:] *= fade_out

        pulse_count = 0
        while self.playing:
            try:
                pulse_count += 1
                _log(f"[Voice] Playing indicator pulse #{pulse_count}")
                # Play pulse using sd.play (separate from recording stream)
                sd.play(pulse.astype(np.float32), sample_rate)
                sd.wait()  # Wait for pulse to finish
                # Pause between pulses
                pause_end = time.time() + pause_duration
                while self.playing and time.time() < pause_end:
                    time.sleep(0.1)
            except Exception as e:
                _log(f"[Voice] Indicator sound error: {e}")
                break


# Global sound instances
_processing_sound = ProcessingSound()
_recording_indicator = RecordingIndicatorSound()


class VoiceRecorder:
    """Handles audio recording with visual feedback."""

    def __init__(self, sample_rate=16000, max_recording_seconds: int = 300,
                 indicator_sound_enabled: bool = True, indicator_sound_volume: float = 0.5,
                 indicator_sound_frequency: int = 880, indicator_sound_pulse_ms: int = 200,
                 indicator_sound_pause_ms: int = 2000,
                 start_beep_enabled: bool = True, start_beep_frequency: int = 880,
                 start_beep_duration_ms: int = 500, start_beep_volume: float = 0.6,
                 stop_beep_enabled: bool = True, stop_beep_frequency: int = 660,
                 stop_beep_duration_ms: int = 300, stop_beep_volume: float = 0.6):
        """
        Initialize voice recorder.

        Args:
            sample_rate: Audio sample rate (default: 16000)
            max_recording_seconds: Max recording time in seconds (default: 300 = 5 minutes), 0 = unlimited
            indicator_sound_enabled: Play quiet sound while recording (default: True)
            indicator_sound_volume: Volume of indicator sound 0.0-1.0 (default: 0.15)
            indicator_sound_frequency: Frequency of indicator pulse in Hz (default: 200)
            indicator_sound_pulse_ms: Duration of each pulse in ms (default: 150)
            indicator_sound_pause_ms: Pause between pulses in ms (default: 800)
            start_beep_enabled: Play beep when recording starts (default: True)
            start_beep_frequency: Start beep frequency in Hz (default: 800)
            start_beep_duration_ms: Start beep duration in ms (default: 50)
            start_beep_volume: Start beep volume 0.0-1.0 (default: 0.3)
            stop_beep_enabled: Play beep when recording stops (default: True)
            stop_beep_frequency: Stop beep frequency in Hz (default: 400)
            stop_beep_duration_ms: Stop beep duration in ms (default: 50)
            stop_beep_volume: Stop beep volume 0.0-1.0 (default: 0.3)
        """
        self.sample_rate = sample_rate
        self.max_recording_seconds = max_recording_seconds
        # Indicator sound settings
        self.indicator_sound_enabled = indicator_sound_enabled
        self.indicator_sound_volume = indicator_sound_volume
        self.indicator_sound_frequency = indicator_sound_frequency
        self.indicator_sound_pulse_ms = indicator_sound_pulse_ms
        self.indicator_sound_pause_ms = indicator_sound_pause_ms
        # Start beep settings
        self.start_beep_enabled = start_beep_enabled
        self.start_beep_frequency = start_beep_frequency
        self.start_beep_duration_ms = start_beep_duration_ms
        self.start_beep_volume = start_beep_volume
        # Stop beep settings
        self.stop_beep_enabled = stop_beep_enabled
        self.stop_beep_frequency = stop_beep_frequency
        self.stop_beep_duration_ms = stop_beep_duration_ms
        self.stop_beep_volume = stop_beep_volume
        # Recording state
        self.recording = False
        self.audio_data = []
        self.stream = None
        self._auto_stop_timer = None
        self._on_auto_stop_callback = None
        self._indicator_sound = None

    def start(self, on_auto_stop=None):
        """
        Start recording audio.

        Args:
            on_auto_stop: Callback function to call when max recording time is reached
        """
        _log("[Voice] VoiceRecorder.start() called")

        if not sd:
            raise RuntimeError("sounddevice not installed. Run: pip install sounddevice soundfile")

        # Update tray status and visual indicator (cursor + icon)
        _update_tray_status("Aufnahme...")
        _set_recording_indicator(True)

        # Play start beep if enabled (configurable)
        _log(f"[Voice] About to play start beep: enabled={self.start_beep_enabled}, freq={self.start_beep_frequency}, vol={self.start_beep_volume}")
        if self.start_beep_enabled:
            play_beep(
                frequency=self.start_beep_frequency,
                duration_ms=self.start_beep_duration_ms,
                volume=self.start_beep_volume
            )
        else:
            _log("[Voice] Start beep disabled in config")

        self.recording = True
        self.audio_data = []
        self._on_auto_stop_callback = on_auto_stop

        def callback(indata, frames, time_info, status):
            if status:
                _log(f"[Voice] Recording status: {status}")
            if self.recording:
                self.audio_data.append(indata.copy())

        self.stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            callback=callback,
            dtype='float32'
        )
        self.stream.start()

        # Start indicator sound if enabled (configurable)
        _log(f"[Voice] indicator_sound_enabled={self.indicator_sound_enabled}, volume={self.indicator_sound_volume}, freq={self.indicator_sound_frequency}, pulse={self.indicator_sound_pulse_ms}ms, pause={self.indicator_sound_pause_ms}ms")
        if self.indicator_sound_enabled:
            self._indicator_sound = RecordingIndicatorSound(
                volume=self.indicator_sound_volume,
                frequency=self.indicator_sound_frequency,
                pulse_ms=self.indicator_sound_pulse_ms,
                pause_ms=self.indicator_sound_pause_ms
            )
            self._indicator_sound.start()
            _log("[Voice] Indicator sound started")
        else:
            _log("[Voice] Indicator sound disabled in config")

        # Start auto-stop timer if max recording time is set
        if self.max_recording_seconds > 0:
            self._auto_stop_timer = threading.Timer(
                self.max_recording_seconds,
                self._auto_stop
            )
            self._auto_stop_timer.daemon = True
            self._auto_stop_timer.start()
            _log(f"[Voice] Recording started... (max {self.max_recording_seconds}s, press hotkey to stop)")
        else:
            _log("[Voice] Recording started... (Press hotkey again to stop)")

    def _auto_stop(self):
        """Called when max recording time is reached."""
        if self.recording:
            _log(f"[Voice] Max recording time ({self.max_recording_seconds}s) reached, auto-stopping...")
            # Play a different beep to indicate auto-stop (double beep)
            play_beep(frequency=600, duration_ms=80, volume=0.3)
            play_beep(frequency=400, duration_ms=80, volume=0.3)

            # Call the callback to process the recording
            if self._on_auto_stop_callback:
                self._on_auto_stop_callback()

    def stop(self) -> bytes:
        """Stop recording and return audio data as WAV bytes."""
        if not self.recording:
            return None

        self.recording = False

        # Reset visual indicator (cursor + icon)
        _set_recording_indicator(False)

        # Cancel auto-stop timer if running
        if self._auto_stop_timer:
            self._auto_stop_timer.cancel()
            self._auto_stop_timer = None

        # Stop indicator sound
        if self._indicator_sound:
            self._indicator_sound.stop()
            self._indicator_sound = None

        if self.stream:
            self.stream.stop()
            self.stream.close()

        # Play stop beep if enabled (configurable)
        if self.stop_beep_enabled:
            play_beep(
                frequency=self.stop_beep_frequency,
                duration_ms=self.stop_beep_duration_ms,
                volume=self.stop_beep_volume
            )

        if not self.audio_data:
            _log("[Voice] No audio data recorded")
            return None

        # Convert to numpy array
        audio = np.concatenate(self.audio_data, axis=0)

        # Save to temporary WAV file
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
            sf.write(tmp.name, audio, self.sample_rate)
            tmp_path = tmp.name

        # Read back as bytes
        with open(tmp_path, 'rb') as f:
            audio_bytes = f.read()

        # Cleanup
        Path(tmp_path).unlink(missing_ok=True)

        _log(f"[Voice] Recording stopped ({len(audio_bytes)} bytes)")

        # Check minimum audio length (< 0.5 seconds is likely noise/empty)
        min_bytes = self.sample_rate * 2 * 0.5  # 0.5 seconds at 16-bit mono
        if len(audio_bytes) < min_bytes:
            _log("[Voice] Recording too short, ignoring")
            return None

        return audio_bytes

    def is_recording(self) -> bool:
        """Check if currently recording."""
        return self.recording


def get_active_window_info() -> dict:
    """
    Get information about the currently active window.

    Returns:
        dict with keys: window_title, process_name, is_outlook, is_browser, browser_url
    """
    result = {
        "window_title": "",
        "process_name": "",
        "is_outlook": False,
        "is_browser": False,
        "browser_url": None,
        "is_outlook_web": False,
        "outlook_message_id": None
    }

    if sys.platform != 'win32' or not win32gui:
        return result

    try:
        # Get foreground window
        hwnd = win32gui.GetForegroundWindow()
        window_title = win32gui.GetWindowText(hwnd)

        # Get process name
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        process = psutil.Process(pid)
        process_name = process.name()

        result["window_title"] = window_title
        result["process_name"] = process_name

        # Check if Outlook desktop
        is_outlook = process_name.lower() in ['outlook.exe', 'outlookmail.exe']
        result["is_outlook"] = is_outlook

        # Check if browser
        browser_processes = ['chrome.exe', 'msedge.exe', 'vivaldi.exe', 'brave.exe', 'firefox.exe']
        is_browser = process_name.lower() in browser_processes
        result["is_browser"] = is_browser

        # If browser, try to get URL via CDP
        if is_browser:
            try:
                from .browser_launcher import (
                    get_active_tab_url,
                    is_outlook_web_url,
                    extract_outlook_message_id
                )

                browser_url = get_active_tab_url()
                result["browser_url"] = browser_url

                if browser_url and is_outlook_web_url(browser_url):
                    result["is_outlook_web"] = True
                    result["outlook_message_id"] = extract_outlook_message_id(browser_url)

            except Exception as e:
                _log(f"[Voice] Error getting browser URL: {e}")

        return result

    except Exception as e:
        _log(f"[Voice] Error getting active window: {e}")
        return result


def transcribe_audio(audio_bytes: bytes, port: int, language: str = "de") -> str:
    """
    Send audio to local /transcribe endpoint.

    Args:
        audio_bytes: WAV audio data
        port: DeskAgent server port
        language: Language code (de, en, etc.)

    Returns:
        Transcribed text or None on error
    """
    if not requests:
        _log("[Voice] requests library not installed")
        return None

    try:
        url = f"http://localhost:{port}/transcribe"
        files = {'audio': ('recording.wav', io.BytesIO(audio_bytes), 'audio/wav')}

        _log("[Voice] Transcribing...")

        # Update tray status
        _update_tray_status("Transkribiere...")

        # Start processing sound
        _processing_sound.start()

        try:
            response = requests.post(url, files=files, timeout=30)
        finally:
            # Always stop the sound
            _processing_sound.stop()

        if response.status_code == 200:
            data = response.json()
            text = data.get('text', '').strip()
            _log(f"[Voice] Transcription: '{text[:100]}...'")

            # Check for empty or hallucinated content
            if not text or len(text) < 3:
                _log("[Voice] Transcription too short, ignoring")
                return None

            # Check for known Whisper hallucinations (URLs, repetitive content)
            hallucination_patterns = [
                'www.', 'http://', 'https://',
                '.com', '.de', '.io', '.org',
                'Untertitel', 'Subtitles', 'Copyright',
                '♪', '...'
            ]
            text_lower = text.lower()
            for pattern in hallucination_patterns:
                if pattern.lower() in text_lower and len(text) < 50:
                    _log(f"[Voice] Detected hallucination pattern '{pattern}', ignoring")
                    return None

            return text
        else:
            _log(f"[Voice] Error: {response.status_code} - {response.text}")
            return None

    except Exception as e:
        _processing_sound.stop()
        _log(f"[Voice] Transcription failed: {e}")
        return None


def paste_text(text: str, press_enter: bool = False):
    """
    Paste text into active application using clipboard.

    Args:
        text: Text to paste
        press_enter: If True, press Enter after pasting
    """
    if not pyperclip:
        _log("[Voice] pyperclip not installed. Run: pip install pyperclip")
        return

    try:
        # Copy text to clipboard
        pyperclip.copy(text)

        # Verify clipboard content
        clipboard_content = pyperclip.paste()
        _log(f"[Voice] Clipboard now contains: '{clipboard_content[:50]}...' ({len(clipboard_content)} chars)")

        # Wait for clipboard to settle
        time.sleep(0.1)

        # Re-activate the foreground window to ensure it has focus
        if sys.platform == 'win32' and win32gui:
            try:
                hwnd = win32gui.GetForegroundWindow()
                window_title = win32gui.GetWindowText(hwnd)
                _log(f"[Voice] Active window: '{window_title[:40]}...'")
                # SetForegroundWindow to ensure focus
                win32gui.SetForegroundWindow(hwnd)
                time.sleep(0.1)
            except Exception as e:
                _log(f"[Voice] Could not set foreground window: {e}")

        # Simulate Ctrl+V using pynput (works better across applications)
        try:
            from pynput.keyboard import Key, Controller
            kb = Controller()
            _log("[Voice] Sending Ctrl+V via pynput...")
            time.sleep(0.05)  # Small delay before key press
            with kb.pressed(Key.ctrl):
                kb.press('v')
                kb.release('v')
            time.sleep(0.1)  # Small delay after key press
        except ImportError:
            _log("[Voice] pynput not available, trying win32api...")
            if sys.platform == 'win32':
                import win32api
                import win32con
                win32api.keybd_event(win32con.VK_CONTROL, 0, 0, 0)
                win32api.keybd_event(ord('V'), 0, 0, 0)
                time.sleep(0.05)
                win32api.keybd_event(ord('V'), 0, win32con.KEYEVENTF_KEYUP, 0)
                win32api.keybd_event(win32con.VK_CONTROL, 0, win32con.KEYEVENTF_KEYUP, 0)
            else:
                _log("[Voice] Cannot simulate Ctrl+V. Install: pip install pynput")

        _log(f"[Voice] Text pasted ({len(text)} chars)")

        # Press Enter if requested
        if press_enter:
            time.sleep(0.1)  # Small delay before Enter
            try:
                from pynput.keyboard import Key, Controller
                kb = Controller()
                _log("[Voice] Pressing Enter...")
                kb.press(Key.enter)
                kb.release(Key.enter)
            except ImportError:
                if sys.platform == 'win32':
                    import win32api
                    import win32con
                    win32api.keybd_event(win32con.VK_RETURN, 0, 0, 0)
                    time.sleep(0.05)
                    win32api.keybd_event(win32con.VK_RETURN, 0, win32con.KEYEVENTF_KEYUP, 0)
                else:
                    _log("[Voice] Cannot simulate Enter. Install: pip install pynput")

    except Exception as e:
        _log(f"[Voice] Error pasting text: {e}")


def copy_selection():
    """
    Copy current selection to clipboard by sending Ctrl+C.

    This allows agents to work with whatever text the user has selected,
    without requiring them to manually copy first.
    """
    _log("[Voice] Copying current selection to clipboard...")

    try:
        from pynput.keyboard import Key, Controller
        kb = Controller()
        time.sleep(0.05)  # Small delay before key press
        with kb.pressed(Key.ctrl):
            kb.press('c')
            kb.release('c')
        time.sleep(0.15)  # Wait for clipboard to update
        _log("[Voice] Selection copied via Ctrl+C")
    except ImportError:
        _log("[Voice] pynput not available, trying win32api...")
        if sys.platform == 'win32':
            import win32api
            import win32con
            win32api.keybd_event(win32con.VK_CONTROL, 0, 0, 0)
            win32api.keybd_event(ord('C'), 0, 0, 0)
            time.sleep(0.05)
            win32api.keybd_event(ord('C'), 0, win32con.KEYEVENTF_KEYUP, 0)
            win32api.keybd_event(win32con.VK_CONTROL, 0, win32con.KEYEVENTF_KEYUP, 0)
            time.sleep(0.15)  # Wait for clipboard to update
        else:
            _log("[Voice] Cannot simulate Ctrl+C. Install: pip install pynput")


def start_agent(agent_name: str, prompt: str, port: int):
    """
    Start an agent via HTTP API.

    Args:
        agent_name: Name of agent to start
        prompt: User prompt for agent
        port: DeskAgent server port
    """
    if not requests:
        _log("[Voice] requests library not installed")
        return

    try:
        url = f"http://localhost:{port}/agent/{agent_name}"
        # Send prompt as _context input (matches AgentInputsRequest schema)
        # Mark as voice-triggered for History tracking
        data = {
            "inputs": {"_context": prompt},
            "triggered_by": "voice",
            "initial_prompt": prompt  # Store voice input for History display
        }

        # Update tray status - agent starting
        _update_tray_status("Agent startet...", agent_name)

        _log(f"[Voice] Starting agent '{agent_name}'...")
        response = requests.post(url, json=data, timeout=5)

        if response.status_code == 200:
            _log(f"[Voice] Agent started successfully")
            # Update tray status - agent running
            # Note: The agent runs asynchronously, so we show "läuft..."
            # The agent execution itself will update status and reset to idle when done
            _update_tray_status("läuft...", agent_name)
        else:
            _log(f"[Voice] Error starting agent: {response.status_code}")
            _set_tray_idle()

    except Exception as e:
        _log(f"[Voice] Error starting agent: {e}")
        _set_tray_idle()


class VoiceHotkeyHandler:
    """Manages system-wide voice input hotkeys."""

    def __init__(self, port: int, config: dict):
        self.port = port
        self.config = config

        # Log all sound settings from config
        _log(f"[Voice] Config: start_beep_enabled={config.get('start_beep_enabled', True)}, "
             f"start_beep_freq={config.get('start_beep_frequency', 800)}, "
             f"start_beep_vol={config.get('start_beep_volume', 0.3)}")
        _log(f"[Voice] Config: indicator_enabled={config.get('indicator_sound_enabled', True)}, "
             f"indicator_vol={config.get('indicator_sound_volume', 0.15)}")
        _log(f"[Voice] Config: stop_beep_enabled={config.get('stop_beep_enabled', True)}, "
             f"stop_beep_freq={config.get('stop_beep_frequency', 400)}, "
             f"stop_beep_vol={config.get('stop_beep_volume', 0.3)}")

        # Get all sound settings from config
        self.recorder = VoiceRecorder(
            max_recording_seconds=config.get('max_recording_seconds', 300),
            # Indicator sound settings
            indicator_sound_enabled=config.get('indicator_sound_enabled', True),
            indicator_sound_volume=config.get('indicator_sound_volume', 0.15),
            indicator_sound_frequency=config.get('indicator_sound_frequency', 200),
            indicator_sound_pulse_ms=config.get('indicator_sound_pulse_ms', 150),
            indicator_sound_pause_ms=config.get('indicator_sound_pause_ms', 800),
            # Start beep settings
            start_beep_enabled=config.get('start_beep_enabled', True),
            start_beep_frequency=config.get('start_beep_frequency', 800),
            start_beep_duration_ms=config.get('start_beep_duration_ms', 50),
            start_beep_volume=config.get('start_beep_volume', 0.3),
            # Stop beep settings
            stop_beep_enabled=config.get('stop_beep_enabled', True),
            stop_beep_frequency=config.get('stop_beep_frequency', 400),
            stop_beep_duration_ms=config.get('stop_beep_duration_ms', 50),
            stop_beep_volume=config.get('stop_beep_volume', 0.3)
        )
        self.processing = False
        self.browser_consent_checked = False
        self.press_enter_on_paste = False  # Set by hotkey, used in _process_recording
        self.start_agent_mode = False  # If True, start agent instead of pasting text
        self.target_agent_name = None  # Agent to start when agent_mode is True
        self.agent_hotkeys = {}  # Maps hotkey -> agent_name (loaded from agents.json)

    def _ensure_browser_integration(self):
        """
        Ensure browser integration is available.

        - Checks if consent is given (configured via Settings > Integrations)
        - Starts browser with separate profile if consented
        """
        # Check if already checked this session
        if self.browser_consent_checked:
            return

        self.browser_consent_checked = True

        # Load browser config
        try:
            from .skills import load_config
            config = load_config()
            browser_config = config.get('browser_integration', {})
        except Exception:
            _log("[Voice] Error loading browser config")
            return

        # Check if browser integration is enabled
        if not browser_config.get('enabled', True):
            return

        # Check if consent is required and given
        require_consent = browser_config.get('require_consent', True)

        if require_consent:
            try:
                from .browser_consent import has_consent
                if not has_consent():
                    # Consent not given - user must enable in Settings > Integrations
                    _log("[Voice] Browser integration not enabled (configure in Settings > Integrations)")
                    return
            except Exception as e:
                _log(f"[Voice] Error checking consent: {e}")
                return

        # Consent given or not required - start browser
        self._start_browser_if_needed(browser_config)

    def _start_browser_if_needed(self, browser_config: dict):
        """Start browser with separate profile if not already running."""
        try:
            from .browser_launcher import (
                is_browser_with_debugging_running,
                launch_browser_with_debugging
            )

            port = browser_config.get('port', 9222)

            # Check if already running
            if is_browser_with_debugging_running(port):
                _log(f"[Voice] Browser already running on port {port}")
                return

            # Start browser with separate profile
            browser_type = browser_config.get('browser', 'chrome')
            separate_profile = browser_config.get('separate_profile', True)

            # Generate profile path
            if separate_profile:
                import tempfile
                user_data_dir = str(Path(tempfile.gettempdir()) / "deskagent-browser")
            else:
                user_data_dir = None

            _log(f"[Voice] Starting {browser_type} with debugging...")
            if separate_profile:
                _log(f"[Voice] Using isolated profile: {user_data_dir}")

            launch_browser_with_debugging(
                browser_type=browser_type,
                port=port,
                url=None,
                user_data_dir=user_data_dir
            )

        except Exception as e:
            _log(f"[Voice] Error starting browser: {e}")

    def toggle_recording(self, press_enter: bool = False, agent_mode: bool = False, agent_name: str = None):
        """Toggle recording on/off (called by hotkey).

        Args:
            press_enter: If True, press Enter after pasting (for hotkey_enter)
            agent_mode: If True, start agent instead of pasting text (for agent_hotkey)
            agent_name: Agent to start when agent_mode is True (from agents.json voice_hotkey)
        """
        _log(f"[Voice] toggle_recording() called: is_recording={self.recorder.is_recording()}, processing={self.processing}")

        if self.processing:
            _log("[Voice] Still processing previous recording...")
            return

        if self.recorder.is_recording():
            # Stop recording and process
            _log("[Voice] Stopping recording...")
            threading.Thread(target=self._process_recording, daemon=True).start()
        else:
            # Start recording - remember mode settings
            _log("[Voice] Starting recording...")
            self.press_enter_on_paste = press_enter
            self.start_agent_mode = agent_mode
            self.target_agent_name = agent_name  # Store target agent for _process_recording
            try:
                # Pass auto-stop callback to process recording when max time is reached
                self.recorder.start(on_auto_stop=lambda: threading.Thread(
                    target=self._process_recording, daemon=True
                ).start())
                _log("[Voice] recorder.start() completed")
            except Exception as e:
                _log(f"[Voice] Error starting recording: {e}")
                import traceback
                _log(f"[Voice] Traceback: {traceback.format_exc()}")

    def _process_recording(self):
        """Process recorded audio (runs in background thread)."""
        self.processing = True
        agent_started = False  # Track if an agent was started

        try:
            # Update status - processing audio
            _update_tray_status("Verarbeite Audio...")

            # Stop recording
            audio_bytes = self.recorder.stop()
            if not audio_bytes:
                _set_tray_idle()
                return

            # Transcribe audio (language is handled server-side, "auto" for auto-detection)
            language = self.config.get('language', 'auto')
            text = transcribe_audio(audio_bytes, self.port, language)

            if not text:
                _log("[Voice] Transcription failed")
                _set_tray_idle()
                return

            # Execute action based on which hotkey was pressed
            if self.start_agent_mode:
                # Agent hotkey was pressed - start the configured agent
                # Use target_agent_name if set (from agents.json voice_hotkey),
                # otherwise fall back to legacy config (outlook_agent)
                agent_name = self.target_agent_name or self.config.get('outlook_agent', 'reply_email')
                _log(f"[Voice] Agent mode: Starting '{agent_name}' agent")

                # Copy current selection to clipboard before starting agent
                # This allows agents to work with selected text without manual copy
                copy_selection()

                start_agent(agent_name, text, self.port)
                agent_started = True
            else:
                # Dictate hotkey was pressed - paste text into active application
                _log(f"[Voice] Dictate mode: Pasting text" + (" + Enter" if self.press_enter_on_paste else ""))
                _update_tray_status("Füge Text ein...")
                paste_text(text, press_enter=self.press_enter_on_paste)

        except Exception as e:
            _log(f"[Voice] Error processing recording: {e}")
            import traceback
            traceback.print_exc()
            _set_tray_idle()  # Reset on error

        finally:
            self.processing = False
            # Reset tray to idle if no agent was started
            # (agents handle their own status lifecycle)
            if not agent_started:
                _set_tray_idle()


def register_voice_hotkey(port: int, config: dict):
    """
    Register system-wide voice input hotkeys.

    Hotkeys:
    - dictate_hotkey: Records voice → transcribes → pastes text
    - dictate_hotkey_enter: Same as above + presses Enter
    - agent_hotkey: Records voice → transcribes → starts configured agent

    Args:
        port: DeskAgent server port
        config: voice_input config from system.json

    Returns:
        VoiceHotkeyHandler instance or None if disabled/unavailable
    """
    _log("[Voice] Registering voice hotkeys...")

    # Check if voice input is available (OpenAI API key configured)
    try:
        from .routes.transcription import is_voice_available
        available, reason = is_voice_available()

        if not available:
            reason_messages = {
                "disabled_in_config": "Voice input disabled in config",
                "openai_not_configured": "OpenAI API key not configured"
            }
            message = reason_messages.get(reason, "Voice input not available")
            _log(f"[Voice] {message}. Voice hotkeys disabled.")
            if reason == "openai_not_configured":
                _log("        Configure API key in config/backends.json under ai_backends.openai.api_key")
            return None
    except Exception as e:
        _log(f"[Voice] Error checking voice availability: {e}")
        return None

    # Check dependencies
    if not sd or not sf or not np:
        _log("[Voice] sounddevice/soundfile not installed. Voice hotkeys disabled.")
        _log("        Install with: pip install sounddevice soundfile numpy")
        return None

    if not requests:
        _log("[Voice] requests not installed. Voice hotkeys disabled.")
        return None

    if not pyperclip:
        _log("[Voice] pyperclip not installed. Dictate mode will not work.")
        _log("        Install with: pip install pyperclip")

    # Import keyboard
    try:
        import keyboard
    except ImportError:
        _log("[Voice] keyboard library not installed. Voice hotkeys disabled.")
        return None

    # Create handler
    handler = VoiceHotkeyHandler(port, config)

    # Track registered hotkeys
    hotkeys_registered = []

    try:
        # Register dictate hotkey (text paste)
        dictate_hotkey = config.get('dictate_hotkey') or config.get('system_hotkey')  # Fallback for old config
        if dictate_hotkey:
            keyboard.add_hotkey(dictate_hotkey, lambda: handler.toggle_recording(press_enter=False, agent_mode=False), suppress=False)
            hotkeys_registered.append(f"{dictate_hotkey.upper()} (Dictate)")
            _log(f"[Voice] Dictate Hotkey: {dictate_hotkey.upper()} → paste text")

        # Register dictate + Enter hotkey
        dictate_hotkey_enter = config.get('dictate_hotkey_enter') or config.get('system_hotkey_enter')  # Fallback
        if dictate_hotkey_enter:
            keyboard.add_hotkey(dictate_hotkey_enter, lambda: handler.toggle_recording(press_enter=True, agent_mode=False), suppress=False)
            hotkeys_registered.append(f"{dictate_hotkey_enter.upper()} (Dictate+Enter)")
            _log(f"[Voice] Dictate Hotkey: {dictate_hotkey_enter.upper()} → paste text + Enter")

        # Register agent-specific hotkeys from agents.json
        try:
            import sys
            from pathlib import Path

            # Add scripts dir to path if needed
            scripts_dir = Path(__file__).parent.parent.parent
            if str(scripts_dir) not in sys.path:
                sys.path.insert(0, str(scripts_dir))

            from config import load_config
            full_config = load_config()
            agents = full_config.get('agents', {})

            for agent_name, agent_cfg in agents.items():
                voice_hotkey = agent_cfg.get('voice_hotkey')
                if voice_hotkey and agent_cfg.get('enabled', True):
                    # Create closure to capture agent_name correctly
                    def make_callback(name):
                        return lambda: handler.toggle_recording(press_enter=False, agent_mode=True, agent_name=name)

                    keyboard.add_hotkey(voice_hotkey, make_callback(agent_name), suppress=False)
                    handler.agent_hotkeys[voice_hotkey] = agent_name
                    display_name = agent_cfg.get('name', agent_name)
                    hotkeys_registered.append(f"{voice_hotkey.upper()} ({display_name})")
                    _log(f"[Voice] Agent Hotkey: {voice_hotkey.upper()} → start '{agent_name}' agent")
        except Exception as e:
            _log(f"[Voice] Error loading agent hotkeys from agents.json: {e}")

        # Legacy: Register single agent hotkey from voice_input config (backward compatibility)
        agent_hotkey = config.get('agent_hotkey')
        # Case-insensitive check if already registered via agents.json
        registered_hotkeys_lower = {hk.lower() for hk in handler.agent_hotkeys.keys()}
        if agent_hotkey and agent_hotkey.lower() not in registered_hotkeys_lower:
            agent_name = config.get('outlook_agent', 'reply_email')
            keyboard.add_hotkey(agent_hotkey, lambda: handler.toggle_recording(press_enter=False, agent_mode=True), suppress=False)
            handler.agent_hotkeys[agent_hotkey] = agent_name  # Track for cleanup
            hotkeys_registered.append(f"{agent_hotkey.upper()} (Agent - Legacy)")
            _log(f"[Voice] Agent Hotkey: {agent_hotkey.upper()} → start '{agent_name}' agent (legacy config)")

        if not hotkeys_registered:
            _log("[Voice] No hotkeys configured - only WebUI voice input")
            return None

        # Store global reference for tray menu
        global _voice_handler
        _voice_handler = handler

        return handler

    except Exception as e:
        _log(f"[Voice] Error registering hotkeys: {e}")
        return None


def get_voice_handler() -> 'VoiceHotkeyHandler | None':
    """Get the global voice handler instance."""
    return _voice_handler


def get_voice_hotkeys() -> dict:
    """
    Get the configured voice hotkeys.

    Returns:
        dict with hotkey names and their key combinations.
        For agent hotkeys, returns dict with agent names as keys.
    """
    if not _voice_handler:
        return {}

    config = _voice_handler.config
    hotkeys = {}

    dictate = config.get('dictate_hotkey') or config.get('system_hotkey')
    if dictate:
        hotkeys['dictate'] = dictate.upper()

    dictate_enter = config.get('dictate_hotkey_enter') or config.get('system_hotkey_enter')
    if dictate_enter:
        hotkeys['dictate_enter'] = dictate_enter.upper()

    # Return all agent hotkeys (from agents.json + legacy config)
    if _voice_handler.agent_hotkeys:
        hotkeys['agents'] = {
            agent_name: hotkey.upper()
            for hotkey, agent_name in _voice_handler.agent_hotkeys.items()
        }

    return hotkeys


def is_voice_enabled() -> bool:
    """Check if voice hotkeys are enabled and handler exists."""
    return _voice_handler is not None


def disable_voice_hotkey():
    """Disable all voice hotkeys (remove keyboard hooks)."""
    global _voice_handler
    if _voice_handler:
        try:
            import keyboard
            config = _voice_handler.config

            # Remove dictate hotkey
            dictate_hotkey = config.get('dictate_hotkey') or config.get('system_hotkey')
            if dictate_hotkey:
                try:
                    keyboard.remove_hotkey(dictate_hotkey)
                except (KeyError, ValueError):
                    pass

            # Remove dictate + Enter hotkey
            dictate_hotkey_enter = config.get('dictate_hotkey_enter') or config.get('system_hotkey_enter')
            if dictate_hotkey_enter:
                try:
                    keyboard.remove_hotkey(dictate_hotkey_enter)
                except (KeyError, ValueError):
                    pass

            # Remove all agent hotkeys (from agents.json + legacy config)
            for hotkey in _voice_handler.agent_hotkeys.keys():
                try:
                    keyboard.remove_hotkey(hotkey)
                except (KeyError, ValueError):
                    pass

            _log("[Voice] Hotkeys disabled")
        except Exception as e:
            _log(f"[Voice] Error disabling hotkeys: {e}")
        _voice_handler = None


def enable_voice_hotkey(port: int, config: dict):
    """Re-enable voice hotkeys."""
    global _voice_handler
    if not _voice_handler:
        _voice_handler = register_voice_hotkey(port, config)
        return _voice_handler is not None
    return True
