"""JARVIS: a voice-first desktop assistant with a typed fallback."""

from dotenv import load_dotenv

import ast
import datetime as dt
import json
import operator
import os
import platform
import queue
import random
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
try:
    import winreg
except ImportError:
    winreg = None
from pathlib import Path

try:
    import pyaudiowpatch as pyaudio
    sys.modules.setdefault("pyaudio", pyaudio)
except ImportError:
    pyaudio = None

try:
    import pyttsx3
except ImportError:
    pyttsx3 = None

try:
    import speech_recognition as sr
except ImportError:
    sr = None

try:
    import pyautogui
except ImportError:
    pyautogui = None

try:
    from google import genai  # modern google-genai SDK
except ImportError:
    genai = None

# Cinematic sci-fi desktop window (CustomTkinter). Imported as JarvisWindow so
# the launch entry point below stays unchanged. ANY failure here (customtkinter
# not installed, broken install, GUI library unavailable) leaves JarvisWindow
# as None so the app falls back to terminal mode instead of crashing.
try:
    from jarvis_sci_fi_ui import SciFiWindow as JarvisWindow
except Exception:
    JarvisWindow = None

APP_NAME = "J.A.R.V.I.S."


def _is_frozen():
    """True when running as a PyInstaller executable."""
    return bool(getattr(sys, "frozen", False))


def app_dir():
    """Directory holding user-facing files.

    Development mode: alongside voice_assistant.py. Frozen one-file builds
    extract into a temporary _MEIPASS directory, so instead we anchor to the
    folder containing JARVIS.exe — letting users drop .env / daily_tasks.txt
    next to wherever the executable lives and have their data persist there.
    """
    if _is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


# Configuration loading happens here (after sys/pathlib are ready) rather than
# at import top so the frozen-build locations above are known. override=True
# ensures a fresh .env value wins over any stale GEMINI_API_KEY left over in
# the Windows/system environment.
load_dotenv(app_dir() / ".env", override=True)

NOTES_FILE = app_dir() / "jarvis_notes.json"
DAILY_TASKS_FILE = Path(
    os.environ.get("JARVIS_DAILY_TASKS_FILE", str(app_dir() / "daily_tasks.txt"))
)
MUSIC_DIR = Path(os.environ.get("JARVIS_MUSIC_DIR", Path.home() / "Music"))
APP_COMMANDS = {
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "paint": "mspaint.exe",
    "task manager": "taskmgr.exe",
    "command prompt": "cmd.exe",
    "control panel": "control.exe",
}


class JarvisAssistant:
    def __init__(self, voice_enabled=True, output_callback=None):
        self.voice_enabled = voice_enabled and pyttsx3 is not None
        self.output_callback = output_callback
        # Optional UI hooks: fired by the TTS worker when playback starts and
        # finishes, letting the sci-fi HUD animate the SPEAKING state.
        self.on_speak_start = None
        self.on_speak_end = None
        self.last_listen_error = ""
        self.last_tts_error = ""
        self.engine = None
        self.tts_queue = queue.Queue()
        self.tts_thread = None
        if self.voice_enabled:
            self.tts_thread = threading.Thread(target=self._tts_worker, daemon=True)
            self.tts_thread.start()
        self.gemini_client = self._init_gemini()
        self.jokes = [
            "Why do programmers prefer dark mode? Because light attracts bugs.",
            "I told my computer I needed a break. It said, 'No problem, I will go to sleep.'",
        ]
        self.speak("As-salamu alaykum Farhan", wait=False)
        daily_tasks = self.load_daily_tasks()
        if daily_tasks:
            self.speak(f" what your Today's tasks:\n{daily_tasks}", wait=False)

    @staticmethod
    def load_daily_tasks():
        try:
            return DAILY_TASKS_FILE.read_text(encoding="utf-8").strip()
        except (FileNotFoundError, OSError):
            return ""

    @staticmethod
    def _init_gemini():
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key or genai is None:
            return None
        try:
            return genai.Client(api_key=api_key)
        except Exception as error:
            print(f"[gemini] Client unavailable: {error}")
            return None

    @staticmethod
    def _classify_gemini_error(error):
        """Bucket a Gemini SDK exception into speech-worthy categories."""
        text = f"{error}".lower()
        if "not found" in text or "404" in text:
            return "retired"
        if "429" in text or "quota" in text or "resource_exhausted" in text:
            return "quota"
        if any(tag in text for tag in (
            "timed out", "timeout", "connection", "network", "getaddrinfo",
            "proxy", "503", "500", "internal error", "temporarily unavailable",
        )):
            return "transient"
        if any(tag in text for tag in (
            "api_key_invalid", "api key not valid", "invalid api key",
            "permission_denied", "unauthenticated", "403", "401",
        )):
            return "rejected"
        return "other"

    def _speak_gemini_failure(self, error):
        kind = self._classify_gemini_error(error)
        spoken = {
            "rejected": "My Gemini access was rejected. The API key appears invalid or lacks permission.",
            "quota": "Gemini answered my handshake, but the request quota is exhausted for now.",
            "retired": "None of my known Gemini models are available anymore. Update my model list.",
            "transient": "I lost the connection to Google mid-request. Please try again shortly.",
        }.get(kind, "I could not reach Gemini. Check your API key and internet connection.")
        print(f"[gemini] Request failed ({kind}): {error}")
        self.speak(spoken)

    @staticmethod
    def _gemini_model_candidates():
        """Newest-first model chain: env override, then known-good names."""
        ordered = [
            os.environ.get("JARVIS_GEMINI_MODEL") or None,
            "gemini-3.6-flash",
            "gemini-3.5-flash",
            "gemini-2.5-flash",
        ]
        unique = []
        for model in ordered:
            if model and model not in unique:
                unique.append(model)
        return tuple(unique)

    def ask_gemini(self, question):
        if not self.gemini_client:
            self.speak("Gemini is not configured. Set GEMINI_API_KEY and restart JARVIS.")
            return

        last_error = None
        for model in self._gemini_model_candidates():
            retries_left = 1
            while True:
                try:
                    response = self.gemini_client.models.generate_content(
                        model=model,
                        contents=question,
                    )
                except Exception as error:
                    last_error = error
                    state = self._classify_gemini_error(error)
                    if state == "retired":
                        print(f"[gemini] {model} unavailable; trying next model.")
                        break                                    # next model
                    if state in {"quota", "transient"} and retries_left:
                        retries_left -= 1
                        time.sleep(1.5 if state == "transient" else 0.8)
                        continue                                 # one patient retry
                    self._speak_gemini_failure(error)            # hard stop
                    return
                try:
                    answer = (response.text or "").strip()
                except ValueError:
                    answer = ""
                self.speak(answer or "Gemini returned an empty response.")
                return
        # Every candidate ended in 'retired'-style failures.
        self._speak_gemini_failure(last_error)

    @staticmethod
    def _init_tts():
        if pyttsx3 is None:
            return None
        try:
            engine = pyttsx3.init()
            voices = engine.getProperty("voices")
            if voices:
                preferred_voice = os.environ.get("JARVIS_VOICE", "Zira").lower()
                selected_voice = next(
                    (voice for voice in voices if preferred_voice in voice.name.lower()),
                    voices[min(1, len(voices) - 1)],
                )
                engine.setProperty("voice", selected_voice.id)
            engine.setProperty("rate", 175)
            return engine
        except Exception as error:
            print(f"[audio] Text-to-speech unavailable: {error}")
            return None

    def _tts_worker(self):
        while True:
            text, finished = self.tts_queue.get()
            if text is None:
                self.tts_queue.task_done()
                return
            playback_failed = False
            try:
                self.engine = self._init_tts()
                if self.engine is None:
                    raise RuntimeError("Text-to-speech engine could not be initialized")
                self._fire_speech_hook("on_speak_start", str(text))
                self.engine.say(text)
                self.engine.runAndWait()
                self.last_tts_error = ""
            except Exception as error:
                playback_failed = True
                self.last_tts_error = str(error)
                print(f"[audio] {error}")
            finally:
                if playback_failed and self.engine:
                    try:
                        self.engine.stop()
                    except Exception:
                        pass
                self.engine = None
                finished.set()
                self.tts_queue.task_done()
                # Notify after waiters so the HUD settles right as speech ends.
                self._fire_speech_hook("on_speak_end", str(text))

    def _fire_speech_hook(self, name, text=None):
        hook = getattr(self, name, None)
        if callable(hook):
            try:
                hook(text)
            except Exception as error:
                print(f"[audio] {name} hook failed: {error}")

    def speak(self, text, wait=True):
        text = str(text).strip()
        if not text:
            return
        print(f"\n  {APP_NAME} > {text}")
        if self.output_callback:
            self.output_callback(text)
        if self.voice_enabled:
            finished = threading.Event()
            self.tts_queue.put((str(text), finished))
            if wait:
                finished.wait()

    def shutdown(self):
        if hasattr(self, "audio_stop_event"):
            self.audio_stop_event.set()
        if self.tts_thread and self.tts_thread.is_alive():
            self.tts_queue.put((None, None))

    @staticmethod
    def hud():
        print("\n" + "=" * 62)
        print("  J.A.R.V.I.S. // NEURAL DESKTOP INTERFACE")
        print("  SYSTEM ONLINE  |  VOICE + TEXT  |  SECURE LOCAL MODE")
        print("=" * 62)

    def greet(self):
        hour = dt.datetime.now().hour
        period = "morning" if hour < 12 else "afternoon" if hour < 18 else "evening"
        self.speak(f"Good {period}. All systems are ready. How can I help?")
        print("  Type 'help' to see available commands. Type 'stop' to exit.")

    @staticmethod
    def input_devices():
        if pyaudio is None:
            return []
        try:
            audio = pyaudio.PyAudio()
            try:
                candidates = []
                for index in range(audio.get_device_count()):
                    device = audio.get_device_info_by_index(index)
                    name = device.get("name", "").lower()
                    if device.get("maxInputChannels", 0) > 0 and not device.get("isLoopbackDevice", False):
                        candidates.append((index, name))
                candidates.sort(key=lambda item: (
                    "microphone" not in item[1],
                    "sound mapper" in item[1] or "primary" in item[1],
                    item[0],
                ))
                return [index for index, _name in candidates]
            finally:
                audio.terminate()
        except (ImportError, OSError):
            return []

    @classmethod
    def find_input_device(cls):
        devices = cls.input_devices()
        return devices[0] if devices else None

    def listen(self, timeout=5, phrase_time_limit=7, typed_fallback=True):
        self.last_listen_error = ""
        if sr is None:
            if typed_fallback:
                try:
                    return input("\n  YOU > ").lower().strip()
                except EOFError:
                    return "stop"
            return ""
        recognizer = sr.Recognizer()
        try:
            device_indexes = self.input_devices()
            if not device_indexes:
                raise OSError("No microphone input device detected")
            audio = None
            open_error = None
            for device_index in device_indexes:
                try:
                    with sr.Microphone(device_index=device_index) as source:
                        recognizer.adjust_for_ambient_noise(source, duration=0.4)
                        print(f"\n  [listening on device {device_index}...]")
                        audio = recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_time_limit)
                    break
                except (OSError, ValueError) as error:
                    open_error = error
            if audio is None:
                raise OSError(f"No microphone could be opened: {open_error}")
            query = recognizer.recognize_google(audio, language="en-in")
            print(f"  YOU > {query}")
            return query.lower().strip()
        except (sr.WaitTimeoutError, sr.UnknownValueError):
            return ""
        except sr.RequestError:
            self.last_listen_error = "Speech recognition network unavailable."
            print("  [network unavailable; switching to typed mode]")
        except Exception as error:
            self.last_listen_error = str(error)
            print(f"  [microphone unavailable: {error}]")

        if typed_fallback:
            try:
                return input("\n  YOU > ").lower().strip()
            except EOFError:
                return "stop"
        return ""

    def start_audio_listener(self, on_command, on_status=None):
        if getattr(self, "audio_thread", None) and self.audio_thread.is_alive():
            return self.audio_thread
        self.audio_stop_event = threading.Event()
        self.audio_thread = threading.Thread(
            target=self._audio_loop,
            args=(on_command, on_status),
            daemon=True,
        )
        self.audio_thread.start()
        return self.audio_thread

    def _audio_loop(self, on_command, on_status):
        if sr is None or pyaudio is None:
            if on_status:
                on_status("Speech listener unavailable; use typed input.")
            return
        device_indexes = self.input_devices()
        if not device_indexes:
            if on_status:
                on_status("No microphone detected; use typed input.")
            return

        recognizer = sr.Recognizer()
        last_error = None
        for device_index in device_indexes:
            try:
                with sr.Microphone(device_index=device_index) as source:
                    recognizer.adjust_for_ambient_noise(source, duration=0.4)
                    if on_status:
                        on_status(f"Listening continuously on device {device_index}...")
                    while not self.audio_stop_event.is_set():
                        try:
                            audio = recognizer.listen(source, timeout=1, phrase_time_limit=6)
                        except sr.WaitTimeoutError:
                            continue
                        try:
                            query = recognizer.recognize_google(audio, language="en-in").lower().strip()
                        except sr.UnknownValueError:
                            continue
                        except sr.RequestError:
                            self.last_listen_error = "Speech recognition network unavailable."
                            if on_status:
                                on_status(self.last_listen_error)
                            self.audio_stop_event.wait(3)
                            continue

                        if query and not self.audio_stop_event.is_set():
                            if on_command(query) is False:
                                self.audio_stop_event.set()
                                return
                return
            except (OSError, ValueError) as error:
                last_error = error

        self.last_listen_error = str(last_error) if last_error else "No microphone could be opened."
        if on_status:
            on_status(f"Microphone unavailable: {self.last_listen_error}")

    def run_continuously(self):
        if sr is None or pyaudio is None:
            self.speak("Continuous listening is unavailable. Speech recognition is not installed.")
            return
        self.audio_stop_event = threading.Event()
        recognizer = sr.Recognizer()
        while not self.audio_stop_event.is_set():
            device_indexes = self.input_devices()
            if not device_indexes:
                self.last_listen_error = "No microphone was detected."
                print(f"  [{self.last_listen_error} Retrying in 3 seconds...]")
                self.audio_stop_event.wait(3)
                continue

            microphone_opened = False
            for device_index in device_indexes:
                if self.audio_stop_event.is_set():
                    return
                try:
                    with sr.Microphone(device_index=device_index) as source:
                        microphone_opened = True
                        print("  Calibrating background noise...")
                        recognizer.adjust_for_ambient_noise(source, duration=1)
                        print(f"  Assistant is actively listening on device {device_index}...")
                        while not self.audio_stop_event.is_set():
                            try:
                                audio = recognizer.listen(source, timeout=1, phrase_time_limit=5)
                            except sr.WaitTimeoutError:
                                continue
                            try:
                                query = recognizer.recognize_google(audio, language="en-in").lower().strip()
                            except sr.UnknownValueError:
                                continue
                            except sr.RequestError:
                                self.last_listen_error = "Speech recognition network unavailable."
                                print(f"  [{self.last_listen_error} Retrying...]")
                                self.audio_stop_event.wait(3)
                                continue

                            if query:
                                print(f"  YOU > {query}")
                                if not self.handle(query):
                                    self.audio_stop_event.set()
                                    return
                    break
                except (OSError, ValueError) as error:
                    self.last_listen_error = str(error)
                    print(f"  [microphone {device_index} unavailable: {error}]")

            if not microphone_opened:
                self.audio_stop_event.wait(3)

    def load_notes(self):
        try:
            return json.loads(NOTES_FILE.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def save_note(self, note):
        notes = self.load_notes()
        notes.append({"text": note, "created": dt.datetime.now().isoformat(timespec="seconds")})
        NOTES_FILE.write_text(json.dumps(notes, indent=2), encoding="utf-8")

    @staticmethod
    def calculate(expression):
        allowed = {
            ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
            ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod,
            ast.USub: operator.neg, ast.UAdd: operator.pos,
        }

        def evaluate(node):
            if isinstance(node, ast.Expression):
                return evaluate(node.body)
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
                return node.value
            if isinstance(node, ast.UnaryOp) and type(node.op) in allowed:
                return allowed[type(node.op)](evaluate(node.operand))
            if isinstance(node, ast.BinOp) and type(node.op) in allowed:
                return allowed[type(node.op)](evaluate(node.left), evaluate(node.right))
            raise ValueError("unsupported expression")

        result = evaluate(ast.parse(expression, mode="eval"))
        if abs(result) > 10**100:
            raise ValueError("result is too large")
        return result

    @staticmethod
    def system_status():
        return (
            f"Operating system: {platform.system()} {platform.release()} | "
            f"Python: {platform.python_version()} | Machine: {platform.machine()}"
        )

    @staticmethod
    def disk_status():
        total, used, free = shutil.disk_usage(Path.home())
        to_gb = lambda value: value / (1024 ** 3)
        return f"Disk space: {to_gb(free):.1f} GB free of {to_gb(total):.1f} GB."

    def play_music(self):
        audio_extensions = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".wma"}
        songs = [
            path for path in MUSIC_DIR.iterdir()
            if path.is_file() and path.suffix.lower() in audio_extensions
        ] if MUSIC_DIR.is_dir() else []
        if not songs:
            self.speak(f"No music files found in {MUSIC_DIR}.")
            return
        song = random.choice(songs)
        self.speak(f"Launching {song.name}.")
        try:
            os.startfile(song)
        except OSError as error:
            print(f"  [launcher error: {error}]")

    @staticmethod
    def launch_local_app(app):
        try:
            subprocess.Popen([app])
            return True
        except OSError as error:
            print(f"  [launcher error: {error}]")
            return False

    def open_folder(self, folder):
        path = Path(folder).expanduser()
        if not path.is_dir():
            self.speak(f"I cannot find the folder {path}.")
            return
        os.startfile(path)
        self.speak(f"Opening {path.name or path}.")

    def pc_control(self, query):
        if query.startswith("open "):
            target = query[5:].strip()
            if target == "settings":
                if platform.system() == "Windows":
                    os.startfile("ms-settings:")
                    self.speak("Opening Settings.")
                else:
                    self.speak("Settings are supported on Windows only.")
                return True
            if target in APP_COMMANDS:
                if self.launch_local_app(APP_COMMANDS[target]):
                    self.speak(f"Opening {target}.")
                return True
            folders = {
                "explorer": Path.home(),
                "home": Path.home(),
                "desktop": Path.home() / "Desktop",
                "documents": Path.home() / "Documents",
                "downloads": Path.home() / "Downloads",
                "music": MUSIC_DIR,
            }
            if target in folders:
                self.open_folder(folders[target])
                return True
        if query in {"lock pc", "lock computer", "lock my pc"}:
            if platform.system() == "Windows":
                subprocess.Popen(["rundll32.exe", "user32.dll,LockWorkStation"])
                return True
            self.speak("PC locking is supported on Windows only.")
            return True
        return False

    def desktop_control(self, query):
        if query in {"mouse position", "where is my mouse", "cursor position"}:
            if pyautogui is None:
                self.speak("Desktop automation is not installed. Install pyautogui first.")
                return True
            x, y = pyautogui.position()
            self.speak(f"The cursor is at {x}, {y}.")
            return True
        if query.startswith("move mouse to "):
            if pyautogui is None:
                self.speak("Desktop automation is not installed. Install pyautogui first.")
                return True
            match = re.fullmatch(r"move mouse to (\d+) (\d+)", query)
            if not match:
                self.speak("Use the format move mouse to X Y.")
                return True
            pyautogui.moveTo(int(match.group(1)), int(match.group(2)), duration=0.25)
            self.speak("Mouse moved.")
            return True
        if query in {"click", "left click", "double click", "right click"}:
            if pyautogui is None:
                self.speak("Desktop automation is not installed. Install pyautogui first.")
                return True
            if query == "double click":
                pyautogui.doubleClick()
            elif query == "right click":
                pyautogui.rightClick()
            else:
                pyautogui.click()
            self.speak(f"{query.title()} complete.")
            return True
        if query.startswith("type "):
            if pyautogui is None:
                self.speak("Desktop automation is not installed. Install pyautogui first.")
                return True
            text = query[5:]
            pyautogui.write(text, interval=0.01)
            self.speak("Text entered.")
            return True
        if query in {"volume up", "volume down", "mute", "volume mute"}:
            if pyautogui is None:
                self.speak("Desktop automation is not installed. Install pyautogui first.")
                return True
            key = {"volume up": "volumeup", "volume down": "volumedown"}.get(query, "volumemute")
            pyautogui.press(key)
            self.speak("Volume control complete.")
            return True
        if query.startswith("press "):
            if pyautogui is None:
                self.speak("Desktop automation is not installed. Install pyautogui first.")
                return True
            key = query[6:].strip()
            if key not in {
                "enter", "escape", "tab", "space", "backspace", "up", "down", "left", "right",
                "volumeup", "volumedown", "volumemute",
            }:
                self.speak("That key is not in the approved keyboard list.")
                return True
            pyautogui.press(key)
            self.speak(f"Pressed {key}.")
            return True
        if query.startswith("scroll "):
            if pyautogui is None:
                self.speak("Desktop automation is not installed. Install pyautogui first.")
                return True
            amount_text = query[7:].strip()
            try:
                amount = int(amount_text)
            except ValueError:
                self.speak("Use a whole number, such as scroll 5 or scroll -5.")
                return True
            if not -20 <= amount <= 20 or amount == 0:
                self.speak("Scroll amount must be between -20 and 20, excluding zero.")
                return True
            pyautogui.scroll(amount)
            self.speak("Scrolled.")
            return True
        shortcut_aliases = {
            "copy": ("ctrl", "c"),
            "paste": ("ctrl", "v"),
            "cut": ("ctrl", "x"),
            "undo": ("ctrl", "z"),
            "save": ("ctrl", "s"),
            "select all": ("ctrl", "a"),
            "show desktop": ("win", "d"),
            "minimize windows": ("win", "d"),
        }
        if query in shortcut_aliases:
            if pyautogui is None:
                self.speak("Desktop automation is not installed. Install pyautogui first.")
                return True
            pyautogui.hotkey(*shortcut_aliases[query])
            self.speak(f"{query.title()} complete.")
            return True
        if query.startswith("hotkey "):
            if pyautogui is None:
                self.speak("Desktop automation is not installed. Install pyautogui first.")
                return True
            hotkey = query[7:].strip().replace(" ", "").split("+")
            approved_hotkeys = {
                ("ctrl", "c"), ("ctrl", "v"), ("ctrl", "x"),
                ("ctrl", "a"), ("ctrl", "z"), ("ctrl", "s"),
                ("alt", "tab"), ("win", "d"),
            }
            if tuple(hotkey) not in approved_hotkeys:
                self.speak("That hotkey is not in the approved list.")
                return True
            pyautogui.hotkey(*hotkey)
            self.speak(f"Hotkey {' plus '.join(hotkey)} complete.")
            return True
        if query in {"screenshot", "take screenshot"}:
            if pyautogui is None:
                self.speak("Desktop automation is not installed. Install pyautogui first.")
                return True
            screenshot_dir = Path.home() / "Pictures" / "JARVIS Screenshots"
            screenshot_dir.mkdir(parents=True, exist_ok=True)
            destination = screenshot_dir / f"jarvis-{dt.datetime.now():%Y%m%d-%H%M%S}.png"
            pyautogui.screenshot(str(destination))
            self.speak(f"Screenshot saved to {destination}.")
            return True
        if query.startswith("create folder "):
            path = Path(query[14:].strip()).expanduser()
            path.mkdir(parents=True, exist_ok=True)
            self.speak(f"Folder ready at {path}.")
            return True
        if query.startswith("open path "):
            path = Path(query[10:].strip().strip('"')).expanduser()
            if path.exists():
                os.startfile(path)
                self.speak(f"Opening {path.name or path}.")
            else:
                self.speak("That path does not exist.")
            return True
        if query.startswith("move file ") and " to " in query:
            source, destination = query[10:].split(" to ", 1)
            source_path = Path(source.strip().strip('"')).expanduser()
            destination_path = Path(destination.strip().strip('"')).expanduser()
            if not source_path.is_file():
                self.speak("The source file does not exist.")
            else:
                destination_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(source_path), str(destination_path))
                self.speak("File moved.")
            return True
        return False

    def handle(self, query):
        query = re.sub(r"[.!?,]+$", "", query.strip().lower()).strip()
        if query.startswith("jarvis "):
            query = query[7:].strip()
        if not query:
            return True
        if query in {"stop", "stop listening", "stop assistant", "exit", "quit", "shutdown"}:
            self.speak("Powering down. See you soon.", wait=False)
            return False
        if query in {"help", "commands", "what can you do"}:
            self.speak("""
  COMMANDS
  time / date              Show the current time or date
  status / system status   Show this machine's system profile
    disk space               Show available space on the home drive
  calculate 12 * (4 + 2)   Safely calculate an expression
    ask <question>           Ask Gemini for an AI response
    move mouse to X Y         Move the cursor
        mouse position             Report the cursor coordinates
    click / type <text>       Control the active window
    press enter               Send an approved key
        volume up / volume down / mute
        copy / paste / cut / undo / save
        select all / show desktop
        scroll 5 / scroll -5      Scroll the active window
        hotkey ctrl+c             Send an approved key combination
    screenshot                Save a desktop screenshot
    create folder <path>      Create a folder
    open path <path>          Open a local file or folder
    move file <src> to <dst>  Move one file
    list files [path]         List files in a folder
    file info <path>          Show a file's size and modified time
  remember <text>          Save a note locally
  read notes               Read saved notes
  open youtube / google    Launch a website
        open github / stackoverflow / spotify
        open calendar / maps / news / reddit
            open email / drive / translate / wikipedia
        open settings / control panel
        open explorer / notepad  Control approved desktop apps
    open desktop / downloads Open common folders
    lock pc                  Lock Windows safely
  search <words>           Search the web
  play music               Launch a random file from your Music folder
  joke / who are you       Personality responses
  stop                     Exit JARVIS
""")
            return True
        if self.pc_control(query):
            return True
        if self.desktop_control(query):
            return True
        if query.startswith("ask "):
            self.ask_gemini(query[4:].strip())
            return True
        if query in {"time", "what time is it", "current time"}:
            self.speak(f"The time is {dt.datetime.now().strftime('%I:%M %p')}.")
        elif query in {"date", "what is the date", "today"}:
            self.speak(f"Today is {dt.datetime.now().strftime('%A, %B %d, %Y')}.")
        elif query in {"status", "system status", "system check", "system info"}:
            self.speak(self.system_status())
        elif query in {"disk space", "free space", "storage"}:
            self.speak(self.disk_status())
        elif query in {"hello", "hi", "hey jarvis", "good morning", "good afternoon", "good evening"}:
            self.speak("Hello. All systems are ready.")
        elif query == "list files" or query.startswith("list files "):
            folder = Path(query[11:].strip().strip('"')) if query.startswith("list files ") else Path.cwd()
            folder = folder.expanduser()
            if not folder.is_dir():
                self.speak("That folder does not exist.")
            else:
                entries = sorted(folder.iterdir(), key=lambda path: (path.is_file(), path.name.lower()))
                listing = [f"FILES IN {folder}"]
                for entry in entries[:50]:
                    marker = "[FILE]" if entry.is_file() else "[DIR] "
                    listing.append(f"  {marker} {entry.name}")
                if len(entries) > 50:
                    listing.append(f"  ... and {len(entries) - 50} more")
                self.speak("\n".join(listing))
                self.speak(f"Found {len(entries)} item{'s' if len(entries) != 1 else ''}.")
        elif query.startswith("file info "):
            path = Path(query[10:].strip().strip('"')).expanduser()
            if not path.is_file():
                self.speak("That file does not exist.")
            else:
                modified = dt.datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
                size_kb = path.stat().st_size / 1024
                self.speak(f"{path.name}: {size_kb:.1f} kilobytes, modified {modified}.")
        elif query.startswith("calculate ") or (query.startswith("what is ") and any(char.isdigit() for char in query)):
            expression = query.split(" ", 1)[1] if query.startswith("calculate ") else query[8:]
            try:
                self.speak(f"The result is {self.calculate(expression)}.")
            except (SyntaxError, ValueError, ZeroDivisionError):
                self.speak("I could not safely calculate that expression.")
        elif query.startswith("remember "):
            note = query[9:].strip()
            if note:
                self.save_note(note)
                self.speak("Memory stored locally.")
        elif query in {"read notes", "show notes", "my notes"}:
            notes = self.load_notes()
            if not notes:
                self.speak("Your local memory is empty.")
            else:
                memory = ["LOCAL MEMORY"]
                memory.extend(
                    f"  {index}. {note['text']} ({note['created']})"
                    for index, note in enumerate(notes, 1)
                )
                self.speak("\n".join(memory))
        elif query in {"note count", "notes count", "how many notes"}:
            count = len(self.load_notes())
            self.speak(f"You have {count} saved note{'s' if count != 1 else ''}.")
        elif query.startswith("search youtube "):
            term = query[15:].strip()
            if term:
                self.speak(f"Searching YouTube for {term}.")
                webbrowser.open("https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(term))
        elif query.startswith("search "):
            term = query[7:].strip()
            if term:
                self.speak(f"Searching for {term}.")
                webbrowser.open("https://www.google.com/search?q=" + urllib.parse.quote_plus(term))
        elif query in {"open youtube", "youtube"}:
            self.speak("Opening YouTube.")
            webbrowser.open("https://www.youtube.com")
        elif query in {"open google", "open browser", "google"}:
            self.speak("Opening Google.")
            webbrowser.open("https://www.google.com")
        elif query in {"open github", "github"}:
            self.speak("Opening GitHub.")
            webbrowser.open("https://github.com")
        elif query in {"open stackoverflow", "stackoverflow", "open stack overflow", "stack overflow"}:
            self.speak("Opening Stack Overflow.")
            webbrowser.open("https://stackoverflow.com")
        elif query in {"open spotify", "spotify"}:
            self.speak("Opening Spotify.")
            webbrowser.open("https://open.spotify.com")
        elif query in {"open calendar", "calendar"}:
            self.speak("Opening Calendar.")
            webbrowser.open("https://calendar.google.com")
        elif query in {"open maps", "maps", "open google maps"}:
            self.speak("Opening Maps.")
            webbrowser.open("https://maps.google.com")
        elif query in {"open news", "news"}:
            self.speak("Opening the news.")
            webbrowser.open("https://news.google.com")
        elif query in {"open reddit", "reddit"}:
            self.speak("Opening Reddit.")
            webbrowser.open("https://www.reddit.com")
        elif query in {"open email", "email", "open gmail", "gmail"}:
            self.speak("Opening email.")
            webbrowser.open("https://mail.google.com")
        elif query in {"open drive", "drive", "google drive"}:
            self.speak("Opening Drive.")
            webbrowser.open("https://drive.google.com")
        elif query in {"open translate", "translate", "google translate"}:
            self.speak("Opening Translate.")
            webbrowser.open("https://translate.google.com")
        elif query in {"open wikipedia", "wikipedia"}:
            self.speak("Opening Wikipedia.")
            webbrowser.open("https://www.wikipedia.org")
        elif query == "weather" or query.startswith("weather in "):
            place = query[11:].strip() if query.startswith("weather in ") else "my location"
            self.speak(f"Searching for weather in {place}.")
            webbrowser.open("https://www.google.com/search?q=" + urllib.parse.quote_plus(f"weather in {place}"))
        elif query == "play music":
            self.play_music()
        elif "joke" in query:
            self.speak(random.choice(self.jokes))
        elif "who are you" in query or "your name" in query:
            self.speak("I am JARVIS, a local Python voice interface with a growing memory.")
        elif self.gemini_client:
            self.ask_gemini(query)
        else:
            self.speak("Command not recognized. Say help to view my capabilities.")
        return True

    def run(self, continuous=False):
        self.hud()
        self.speak("Starting neural interface.")
        time.sleep(0.3)
        if continuous:
            self.run_continuously()
            return
        if sr is None or pyaudio is None or not self.input_devices():
            print("  Audio listener unavailable. Falling back to typed commands.")
            while self.handle(self.listen()):
                pass
            return

        self.start_audio_listener(
            lambda query: self.handle(query),
            lambda message: print(f"  [wake word] {message}"),
        )
        try:
            while self.audio_thread.is_alive():
                time.sleep(0.2)
        except KeyboardInterrupt:
            self.shutdown()


# The classic desktop window was replaced by the cinematic sci-fi HUD in
# jarvis_sci_fi_ui.py, imported at the top of this file as `JarvisWindow`.
def configure_windows_startup():
    if sys.platform != "win32" or winreg is None:
        return
    try:
        if getattr(sys, "frozen", False):
            startup_command = f'"{sys.executable}" --continuous'
        else:
            startup_command = f'"{sys.executable}" "{Path(__file__).resolve()}" --continuous'
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE,
        ) as startup_key:
            winreg.SetValueEx(startup_key, "JARVIS", 0, winreg.REG_SZ, startup_command)
    except OSError as error:
        print(f"[startup] Could not register JARVIS for Windows login: {error}")


def self_test():
    assistant = JarvisAssistant(voice_enabled=False)
    assert assistant.calculate("12 * (4 + 2)") == 72
    assert "Python:" in assistant.system_status()
    print("JARVIS self-test: PASS")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    else:
        configure_windows_startup()
        try:
            if "--terminal" in sys.argv or "--continuous" in sys.argv:
                JarvisAssistant().run(continuous="--continuous" in sys.argv)
            elif JarvisWindow is None:
                print("[ui] sci-fi HUD unavailable (customtkinter missing or broken); falling back to terminal mode.")
                print("     Enable the sci-fi HUD with: python -m pip install customtkinter")
                JarvisAssistant().run()
            else:
                JarvisWindow().run()
        except KeyboardInterrupt:
            print("\nJARVIS terminated by user.")
