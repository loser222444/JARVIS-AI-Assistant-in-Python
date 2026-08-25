"""JARVIS: a voice-first desktop assistant with a typed fallback."""

import ast
import datetime as dt
import json
import math
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
from pathlib import Path

import tkinter as tk
from tkinter import scrolledtext

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
    from google import genai
except ImportError:
    genai = None

APP_NAME = "J.A.R.V.I.S."
NOTES_FILE = Path(__file__).with_name("jarvis_notes.json")
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

    def ask_gemini(self, question):
        if not self.gemini_client:
            self.speak("Gemini is not configured. Set GEMINI_API_KEY and restart JARVIS.")
            return
        try:
            response = self.gemini_client.models.generate_content(
                model="gemini-2.5-flash",
                contents=question,
            )
            answer = (response.text or "Gemini returned an empty response.").strip()
            self.speak(answer)
        except Exception as error:
            print(f"[gemini] Request failed: {error}")
            self.speak("I could not reach Gemini. Check your API key and internet connection.")

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
        query = query.strip().lower()
        if query.startswith("jarvis "):
            query = query[7:].strip()
        if not query:
            return True
        if query in {"stop", "stop listening", "stop assistant", "exit", "quit", "shutdown"}:
            self.speak("Powering down. See you soon.")
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
        else:
            self.speak("Command not recognized. Say help to view my capabilities.")
        return True

    def run(self):
        self.hud()
        self.speak("Starting neural interface.")
        time.sleep(0.3)
        while self.handle(self.listen()):
            pass


class JarvisGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("J.A.R.V.I.S. // Neural Interface")
        self.root.geometry("1180x760")
        self.root.minsize(900, 620)
        self.root.configure(bg="#030a10")
        self.assistant = JarvisAssistant(voice_enabled=True, output_callback=self.write_assistant_log)
        self.command_running = False
        self.voice_running = False
        self.audio_mode = "idle"
        self.wave_phase = 0
        self.build_interface()
        self.write_log("SYSTEM ONLINE // AWAITING INPUT", "system")
        self.animate_hud()
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def build_interface(self):
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(1, weight=1)
        self.header = tk.Canvas(self.root, height=92, bg="#030a10", highlightthickness=0)
        self.header.grid(row=0, column=0, sticky="ew")
        self.header.bind("<Configure>", self.draw_header)

        body = tk.Frame(self.root, bg="#030a10")
        body.grid(row=1, column=0, sticky="nsew", padx=28, pady=(0, 24))
        body.grid_columnconfigure(0, weight=3)
        body.grid_columnconfigure(1, weight=2)
        body.grid_rowconfigure(1, weight=1)

        self.hud = tk.Canvas(body, bg="#06121a", highlightthickness=0)
        self.hud.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=(0, 18))
        self.hud.bind("<Configure>", self.draw_hud)
        self.hud.create_text(26, 24, text="PRIMARY COGNITIVE CORE", anchor="w",
                             fill="#5de8dc", font=("Consolas", 10, "bold"))

        history_frame = tk.Frame(body, bg="#06121a")
        history_frame.grid(row=0, column=1, sticky="nsew")
        history_frame.grid_rowconfigure(1, weight=1)
        history_frame.grid_columnconfigure(0, weight=1)
        tk.Label(history_frame, text="COMMAND HISTORY // LOCAL", anchor="w",
                 font=("Consolas", 10, "bold"), fg="#5de8dc", bg="#06121a").grid(
                     row=0, column=0, sticky="ew", padx=18, pady=(18, 10))
        self.history = scrolledtext.ScrolledText(
            history_frame, bg="#041019", fg="#f0c978", insertbackground="#5de8dc",
            relief="flat", borderwidth=0, wrap="word", font=("Consolas", 10),
            padx=16, pady=14, highlightthickness=1, highlightbackground="#174753",
        )
        self.history.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 14))
        self.history.configure(state="disabled")

        content = tk.Frame(body, bg="#06121a")
        content.grid(row=1, column=1, sticky="nsew")
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(1, weight=1)
        tk.Label(content, text="LIVE RESPONSE STREAM", anchor="w", font=("Consolas", 9, "bold"),
                 fg="#5de8dc", bg="#06121a").grid(row=0, column=0, sticky="ew", padx=18, pady=(14, 8))
        self.log = scrolledtext.ScrolledText(content, bg="#041019", fg="#d7f7f2",
                                             insertbackground="#5de8dc", relief="flat",
                                             font=("Consolas", 10), padx=16, pady=14,
                                             highlightthickness=1, highlightbackground="#174753")
        self.log.grid(row=1, column=0, sticky="nsew", padx=14)
        self.log.tag_configure("system", foreground="#62e6d5")
        self.log.tag_configure("user", foreground="#f2c879")
        self.log.tag_configure("assistant", foreground="#d7f7f2")
        self.log.configure(state="disabled")

        controls = tk.Frame(body, bg="#030a10")
        controls.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(18, 0))
        controls.grid_columnconfigure(0, weight=1)
        self.command = tk.Entry(controls, bg="#061b25", fg="#d7f7f2", insertbackground="#5de8dc",
                    relief="flat", font=("Consolas", 12), highlightthickness=1,
                    highlightbackground="#1a5860", highlightcolor="#5de8dc")
        self.command.grid(row=0, column=0, sticky="ew", ipady=10, padx=(0, 10))
        self.command.bind("<Return>", lambda _event: self.submit())
        self.action_button(controls, "TRANSMIT", self.submit, row=0, column=1)
        self.voice_button = self.action_button(controls, "VOICE LINK", self.start_voice, row=0, column=2)

    def action_button(self, parent, label, action, row=None, column=None):
        button = tk.Button(parent, text=label, command=action, bg="#082c36", fg="#5de8dc",
                           activebackground="#105b61", activeforeground="#ffffff", relief="flat",
                           bd=0, font=("Consolas", 9, "bold"), padx=14, pady=10, cursor="hand2",
                           highlightthickness=1, highlightbackground="#1c6970")
        if row is None:
            button.pack(fill="x", padx=14, pady=4)
        else:
            button.grid(row=row, column=column, padx=(0 if column == 1 else 8, 0), sticky="ew")
        return button

    def write_log(self, text, tag):
        self.log.configure(state="normal")
        self.log.insert("end", f"\n  {text}\n", tag)
        self.log.see("end")
        self.log.configure(state="disabled")

    def write_history(self, query):
        self.history.configure(state="normal")
        self.history.insert("end", f"> {query}\n")
        self.history.see("end")
        self.history.configure(state="disabled")

    def write_assistant_log(self, text):
        self.audio_mode = "speaking"
        self.root.after(0, lambda: self.write_log(f"{APP_NAME} > {text}", "assistant"))
        self.root.after(0, lambda: self.root.after(1700, self.reset_audio_mode))

    def reset_audio_mode(self):
        if self.audio_mode == "speaking":
            self.audio_mode = "idle"

    def draw_header(self, _event=None):
        width = self.header.winfo_width()
        self.header.delete("all")
        self.header.create_text(28, 28, text="J.A.R.V.I.S.", anchor="w", fill="#72f5e5",
                                font=("Consolas", 25, "bold"))
        self.header.create_text(30, 58, text="NEURAL DESKTOP INTERFACE  //  SECURE LOCAL MODE",
                                anchor="w", fill="#5b8793", font=("Consolas", 9))
        self.header.create_line(28, 82, max(28, width - 28), 82, fill="#29b8b4", width=2)
        self.header.create_line(max(28, width - 210), 82, max(28, width - 28), 82, fill="#f0c978", width=2)

    def draw_hud(self, _event=None):
        width, height = self.hud.winfo_width(), self.hud.winfo_height()
        if width < 10 or height < 10:
            return
        self.hud.delete("dynamic")
        cx, cy = width * 0.48, height * 0.54
        radius = min(width, height) * 0.28
        for offset, color in ((0, "#1e8f91"), (9, "#115b68"), (22, "#0c3a49")):
            self.hud.create_oval(cx - radius - offset, cy - radius - offset,
                                 cx + radius + offset, cy + radius + offset,
                                 outline=color, width=1, tags="dynamic")
        self.hud.create_arc(cx - radius - 10, cy - radius - 10, cx + radius + 10, cy + radius + 10,
                            start=(self.wave_phase * 3) % 360, extent=78, outline="#f0c978",
                            width=2, tags="dynamic")
        self.hud.create_text(cx, cy - 12, text="J", fill="#76fff0", font=("Consolas", 48, "bold"), tags="dynamic")
        self.hud.create_text(cx, cy + 36, text="CORE ONLINE", fill="#5de8dc", font=("Consolas", 9, "bold"), tags="dynamic")
        for index in range(32):
            angle = (index / 32) * 6.283
            inner = radius + 30
            outer = inner + (12 if index % 4 == 0 else 5)
            self.hud.create_line(cx + inner * math.cos(angle), cy + inner * math.sin(angle),
                                 cx + outer * math.cos(angle), cy + outer * math.sin(angle),
                                 fill="#3faaa5" if index % 4 == 0 else "#174c59", tags="dynamic")
        self.hud.create_text(26, height - 28, text=f"AUDIO STATE  //  {self.audio_mode.upper()}", anchor="w",
                             fill="#f0c978" if self.audio_mode != "idle" else "#6e9fa5",
                             font=("Consolas", 9, "bold"), tags="dynamic")
        self.hud.create_text(width - 26, height - 28, text="LATENCY  024MS  //  LOCAL", anchor="e",
                             fill="#527e89", font=("Consolas", 8), tags="dynamic")
        bars = 30
        bar_width, gap = max(2, (width * 0.56) / bars), 3
        start_x = cx - (bars * (bar_width + gap)) / 2
        for index in range(bars):
            if self.audio_mode == "idle":
                magnitude = 4 + abs(((index + self.wave_phase) % 9) - 4) * 2
            else:
                magnitude = 9 + ((index * 13 + self.wave_phase * 7) % 32)
            self.hud.create_rectangle(start_x + index * (bar_width + gap), cy + radius + 58 - magnitude,
                                       start_x + index * (bar_width + gap) + bar_width, cy + radius + 58,
                                       fill="#38d8cf", outline="", tags="dynamic")

    def animate_hud(self):
        self.wave_phase = (self.wave_phase + 1) % 360
        self.draw_hud()
        self.root.after(55, self.animate_hud)

    def submit(self):
        query = self.command.get().strip()
        if not query or self.command_running:
            return
        self.command.delete(0, "end")
        self.write_log(f"YOU  > {query}", "user")
        self.write_history(query)
        self.set_command_state(False)
        self.command_running = True
        threading.Thread(target=self.process_command, args=(query,), daemon=True).start()

    def process_command(self, query):
        keep_running = self.assistant.handle(query)
        self.root.after(0, lambda: self.command_finished(keep_running))

    def command_finished(self, keep_running):
        self.command_running = False
        self.set_command_state(True)
        if not keep_running:
            self.root.after(350, self.close)

    def set_command_state(self, enabled):
        state = "normal" if enabled else "disabled"
        self.command.configure(state=state)

    def close(self):
        self.assistant.shutdown()
        self.root.destroy()

    def start_voice(self):
        if self.command_running or self.voice_running:
            return
        self.voice_running = True
        self.audio_mode = "listening"
        self.set_command_state(False)
        self.voice_button.configure(state="disabled", text="LISTENING...")
        self.write_log("Listening for a voice command...", "system")
        threading.Thread(target=self.capture_voice, daemon=True).start()

    def capture_voice(self):
        query = self.assistant.listen(typed_fallback=False)
        self.root.after(0, lambda: self.finish_voice_capture(query))

    def finish_voice_capture(self, query):
        self.voice_running = False
        self.reset_audio_mode()
        if query:
            self.write_log(f"YOU  > {query}", "user")
            self.write_history(query)
            self.submit_voice(query)
        else:
            message = self.assistant.last_listen_error or "No voice command detected."
            self.write_log(f"VOICE LINK // {message}", "system")
            self.set_command_state(True)
        self.voice_button.configure(state="normal", text="VOICE LINK")

    def submit_voice(self, query):
        if self.command_running:
            return
        self.command_running = True
        self.set_command_state(False)
        threading.Thread(target=self.process_command, args=(query,), daemon=True).start()

    def run(self):
        self.root.mainloop()


def self_test():
    assistant = JarvisAssistant(voice_enabled=False)
    assert assistant.calculate("12 * (4 + 2)") == 72
    assert "Python:" in assistant.system_status()
    print("JARVIS self-test: PASS")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    elif "--terminal" in sys.argv:
        try:
            JarvisAssistant().run()
        except KeyboardInterrupt:
            print("\nJARVIS terminated by user.")
    else:
        try:
            JarvisGUI().run()
        except KeyboardInterrupt:
            print("\nJARVIS terminated by user.")