"""JARVIS cinematic sci-fi interface built with CustomTkinter.

Movie-style HUD featuring an animated arc-reactor core, neon glow effects,
sonar ripples while listening, scan sweeps while thinking, live telemetry,
and a typewriter mission log. Requires `pip install customtkinter`.
"""

import datetime as dt
import math
import platform
import random
import sys
import threading

if platform.system() == "Windows":
    import ctypes

try:
    import customtkinter as ctk
except ImportError as error:
    # Fail loudly and precisely AT THE ROOT CAUSE. Setting ctk = None here
    # would instead crash later at `class SciFiWindow(ctk.CTk)` with the
    # cryptic "'NoneType' object has no attribute 'CTk'" message.
    raise ImportError(
        "The sci-fi HUD requires the 'customtkinter' package.\n"
        "Install it into THIS interpreter with:\n"
        "    python -m pip install customtkinter\n"
        f"(running interpreter: {sys.executable})"
    ) from error


# ---------------------------------------------------------------- palette --
BG_DEEP = "#04070d"        # near-black space blue (app backdrop)
BG_PANEL = "#070d16"       # side panels
BG_CARD = "#0a1320"        # sunken consoles
BG_CONSOLE = "#050b12"     # chat console background
EDGE = "#122334"           # hairline borders
GRID = "#0b1622"

CYAN = "#00e5ff"           # primary neon
CYAN_SOFT = "#39cfe8"
CYAN_DIM = "#0a4652"
CYAN_INK = "#062228"

GOLD = "#ffc857"           # speaking / warm highlights
GOLD_DIM = "#5c4713"
MAGENTA = "#ff4fd8"        # secondary scan accent
RED = "#ff3b57"            # alert
GREEN = "#38ffb0"          # mic online

TEXT = "#d7ecf5"
TEXT_MUTED = "#5f7d90"
TEXT_FAINT = "#33475a"

FONT_MONO = "Consolas"
FONT_UI = "Segoe UI"

STATE_IDLE = "idle"
STATE_LISTENING = "listening"
STATE_THINKING = "thinking"
STATE_SPEAKING = "speaking"
STATE_OFFLINE = "offline"

STATE_LABELS = {
    STATE_IDLE: "SYSTEM STANDBY",
    STATE_LISTENING: "LISTENING . . .",
    STATE_THINKING: "PROCESSING QUERY",
    STATE_SPEAKING: "RESPONDING",
    STATE_OFFLINE: "VOICE INPUT OFFLINE — TEXT MODE",
}

MAIN_TICK_MS = 40          # ~25 fps master animation loop
CLOCK_TICK_MS = 250
TELEMETRY_TICK_MS = 2000


def mix(color_a, color_b, ratio):
    """Blend two hex colors; ratio 0 -> a, 1 -> b."""
    ratio = max(0.0, min(1.0, ratio))
    a = (int(color_a[1:3], 16), int(color_a[3:5], 16), int(color_a[5:7], 16))
    b = (int(color_b[1:3], 16), int(color_b[3:5], 16), int(color_b[5:7], 16))
    blended = (
        int(round(a[i] * (1 - ratio) + b[i] * ratio))
        for i in range(3)
    )
    return "#{:02x}{:02x}{:02x}".format(*blended)


def fade_to_bg(color, ratio, bg=BG_PANEL):
    """Fade a neon color toward a dark background (fake transparency)."""
    return mix(bg, color, ratio)



APP_TITLE = "J.A.R.V.I.S. // NEURAL DESKTOP INTERFACE"

_ASSISTANT_CLASS_CACHE = None


def _assistant_class():
    """Lazily resolve JarvisAssistant (avoids an import cycle)."""
    global _ASSISTANT_CLASS_CACHE
    if _ASSISTANT_CLASS_CACHE is None:
        try:
            from voice_assistant import JarvisAssistant

            _ASSISTANT_CLASS_CACHE = JarvisAssistant
        except ImportError:
            _ASSISTANT_CLASS_CACHE = None
    return _ASSISTANT_CLASS_CACHE


class DemoAssistant:
    """Minimal stand-in so the HUD can be previewed without the core."""

    def __init__(self, voice_enabled=True, output_callback=None):
        self.voice_enabled = False
        self.gemini_client = True
        self.output_callback = output_callback or (lambda text: print(f"JARVIS > {text}"))

    def start_audio_listener(self, on_command, on_status=None):
        if on_status:
            on_status("Demo mode: voice listener disabled.")

    def handle(self, query):
        self.output_callback(f"Demo echo for '{query}'. The neural core is offline.")
        return True

    def shutdown(self):
        pass


from collections import deque

import datetime as dt
import math
import os
import platform
import queue
import random
import sys
import threading
import time
import tkinter as tk

try:
    from pathlib import Path
except ImportError:
    Path = None

if platform.system() == "Windows":
    try:
        import ctypes
    except ImportError:
        ctypes = None
else:
    ctypes = None

QUICK_CHIPS = (
    ("TIME", "time"),
    ("DATE", "date"),
    ("STATUS", "system status"),
    ("HELP", "help"),
    ("MUSIC", "play music"),
    ("JOKE", "joke"),
)


class SciFiWindow(ctk.CTk):
    """Cinematic HUD around a live JarvisAssistant instance."""

    def __init__(self):
        # CustomTkinter 6 validates constructor kwargs, so the HUD is
        # configured through setup() instead of custom __init__ arguments.
        super().__init__(fg_color=BG_DEEP)

    def setup(
        self,
        voice_enabled=True,
        auto_listen=True,
        boot_sequence=True,
    ):
        """Configure and assemble the HUD. Call once, before run()."""
        self._closing = False
        self._turn = 0
        self.mic_enabled = True
        self.hud_state = STATE_IDLE
        self.auto_listen = auto_listen
        self.boot_sequence = boot_sequence
        self.pending_output = []
        self.console_queue = deque()
        self.log_worker_active = False
        self._events = queue.Queue()
        self.listener_ok = False
        self.voice_pending_speak = 0
        self._typing_mark_counter = 0
        self._ripples = []
        self._eq_values = [random.uniform(0.05, 0.18) for _ in range(27)]
        self._eq_targets = list(self._eq_values)
        self._next_eq_target_at = 0.0
        self._next_ripple_at = 0.0

        ctk.set_appearance_mode("dark")

        # Core assistant; responses are marshalled onto the UI thread.
        core = _assistant_class() or DemoAssistant
        self.assistant = core(
            voice_enabled=voice_enabled,
            output_callback=self.schedule_output,
        )
        self.ai_online = bool(getattr(self.assistant, "gemini_client", None))
        self.voice_on = bool(getattr(self.assistant, "voice_enabled", False))

        self.title(APP_TITLE)
        self.geometry(self._fit_geometry())
        self.minsize(920, 600)
        self.protocol("WM_DELETE_WINDOW", self.close)

        self.build_header()
        self.build_body()
        self.bind_events()

        for text in self.pending_output:
            self.log_line("jarvis", text)
        self.pending_output.clear()
        self.attach_tts_hooks()

        self.update_clock()
        self.refresh_telemetry()
        self.master_tick()

        if self.boot_sequence:
            self.run_boot_sequence()
        if self.auto_listen:
            self.after(150, self.start_voice_listener)
        self._built = True

    # ------------------------------------------------------------ helpers --
    def _fit_geometry(self):
        """Center a large HUD on the screen without overflowing it."""
        try:
            self.update_idletasks()
            screen_w = self.winfo_screenwidth()
            screen_h = self.winfo_screenheight()
        except Exception:
            return "1080x680+80+60"
        width = min(int(screen_w * 0.92), 1120)
        height = min(int(screen_h * 0.92), 700)
        x = max((screen_w - width) // 2, 0)
        y = max((screen_h - height) // 2 - 12, 0)
        return f"{width}x{height}+{x}+{y}"

    def schedule(self, fn, *args, delay_ms=0):
        """Queue fn(*args) for execution on the Tk main loop.

        Safe to call from ANY thread: instead of after(), which is not
        reliably callable from workers on modern Tcl builds, events are
        pushed onto a lock-free queue drained by master_tick().
        """
        due = time.perf_counter() * 1000.0 + max(int(delay_ms), 0)
        try:
            self._events.put((due, fn, args))
        except Exception as error:
            print(f"[ui] failed to schedule {getattr(fn, '__name__', fn)}: {error}")

    def process_events(self):
        """Execute every mature queued callback; re-queue future-dated ones."""
        if self._closing:
            return
        now_ms = time.perf_counter() * 1000.0
        deferred = []
        while True:
            try:
                due, fn, args = self._events.get_nowait()
            except queue.Empty:
                break
            if due > now_ms:
                deferred.append((due, fn, args))
                continue
            try:
                fn(*args)
            except Exception as error:
                print(f"[ui] callback error in {getattr(fn, '__name__', fn)}: {error}")
        for item in deferred:
            self._events.put(item)

    def schedule_output(self, text):
        """Thread entry point used by JarvisAssistant.output_callback."""
        self.schedule(self.on_assistant_output, str(text))

    # ---------------------------------------------------------- scaffolding --
    def build_header(self):
        """Top bar: LED cluster, wordmark, live clock."""
        header = ctk.CTkFrame(self, fg_color=BG_PANEL, corner_radius=0, height=78)
        header.pack(fill="x")
        header.pack_propagate(False)

        hairline = ctk.CTkFrame(self, fg_color=EDGE, corner_radius=0, height=1)
        hairline.pack(fill="x")

        self.led_canvas = tk.Canvas(
            header, width=168, height=56, bg=BG_PANEL,
            highlightthickness=0, bd=0,
        )
        self.led_canvas.place(x=18, y=10)

        wordmark = ctk.CTkLabel(
            header, text="J.A.R.V.I.S.", justify="left",
            font=(FONT_UI, 26, "bold"), text_color=TEXT,
        )
        wordmark.place(x=205, y=8)

        subtitle = ctk.CTkLabel(
            header, text="NEURAL DESKTOP INTERFACE  //  BUILD 3.7",
            justify="left",
            font=(FONT_MONO, 10), text_color=CYAN_SOFT,
        )
        subtitle.place(x=207, y=46)

        self.clock_label = ctk.CTkLabel(
            header, text="--:--:--",
            font=(FONT_MONO, 26, "bold"), text_color=CYAN,
        )
        self.clock_label.place(relx=1.0, x=-116, y=8)

        self.date_label = ctk.CTkLabel(
            header, text="--------- ----------",
            font=(FONT_MONO, 11), text_color=TEXT_MUTED,
        )
        self.date_label.place(relx=1.0, x=-118, y=48)

    def build_left_panel(self, body):
        """Arc-reactor core, state readout, telemetry gauges, equalizer."""
        left = ctk.CTkFrame(body, fg_color=BG_PANEL, corner_radius=12, width=330)
        left.pack(side="left", fill="y", padx=(14, 6), pady=12)
        left.pack_propagate(False)

        inner = ctk.CTkFrame(left, fg_color="transparent")
        inner.pack(expand=True, fill="both", padx=16, pady=(14, 12))

        self.reactor = tk.Canvas(
            inner, width=296, height=296, bg=BG_CARD,
            highlightthickness=0, bd=0,
        )
        self.reactor.pack()

        glow_edge = ctk.CTkFrame(inner, fg_color=EDGE, corner_radius=0, height=1)
        glow_edge.pack(fill="x", pady=(8, 10))

        self.state_label = ctk.CTkLabel(
            inner, text=STATE_LABELS[STATE_IDLE],
            font=(FONT_UI, 14, "bold"), text_color=CYAN,
        )
        self.state_label.pack(pady=(0, 6))

        self.telemetry = tk.Canvas(
            inner, width=280, height=164, bg=BG_CARD,
            highlightthickness=0, bd=0,
        )
        self.telemetry.pack(fill="x", pady=(2, 4))

        self.equalizer = tk.Canvas(
            inner, width=280, height=70, bg=BG_CARD,
            highlightthickness=0, bd=0,
        )
        self.equalizer.pack(fill="x", pady=(4, 0))

    def build_right_panel(self, body):
        """Mission log, quick-command chips, and the command input bar."""
        right = ctk.CTkFrame(body, fg_color="transparent")
        right.pack(side="left", fill="both", expand=True, padx=(6, 14), pady=12)

        self.chat = ctk.CTkTextbox(
            right,
            fg_color=BG_CONSOLE,
            text_color=TEXT,
            font=(FONT_MONO, 12),
            wrap="word",
            corner_radius=10,
            border_width=1,
            border_color=EDGE,
        )
        self.chat.pack(fill="both", expand=True)
        self._configure_console_tags()

        chips = ctk.CTkFrame(right, fg_color="transparent")
        chips.pack(fill="x", pady=(10, 0))
        self.chip_buttons = {}
        for index, (label, command_text) in enumerate(QUICK_CHIPS):
            button = ctk.CTkButton(
                chips,
                text=label,
                width=86,
                height=28,
                fg_color="transparent",
                border_width=1,
                border_color=CYAN_DIM,
                text_color=CYAN_SOFT,
                hover_color=CYAN_INK,
                font=(FONT_UI, 11, "bold"),
                corner_radius=6,
                command=lambda c=command_text: self.send_command(c),
            )
            button.pack(side="left", padx=(0 if index == 0 else 8, 0))
            self.chip_buttons[label] = button

        input_bar = ctk.CTkFrame(right, fg_color="transparent")
        input_bar.pack(fill="x", pady=(12, 0))

        prompt = ctk.CTkLabel(
            input_bar, text="▍>", width=34,
            font=(FONT_MONO, 16, "bold"), text_color=GOLD,
        )
        prompt.pack(side="left")

        self.entry = ctk.CTkEntry(
            input_bar,
            placeholder_text="Type a command, or speak your request . . .",
            height=40,
            font=(FONT_MONO, 13),
            fg_color=BG_CONSOLE,
            border_width=1,
            border_color=CYAN_DIM,
            text_color=TEXT,
            placeholder_text_color=TEXT_FAINT,
            corner_radius=8,
        )
        self.entry.pack(side="left", fill="x", expand=True, padx=(2, 10))

        self.send_button = ctk.CTkButton(
            input_bar,
            text="TRANSMIT",
            width=112,
            height=40,
            fg_color=CYAN_INK,
            border_width=1,
            border_color=CYAN,
            text_color=CYAN,
            hover_color="#0a3a52",
            font=(FONT_UI, 12, "bold"),
            corner_radius=8,
            command=self.submit_typed_command,
        )
        self.send_button.pack(side="left")

        self.mic_button = ctk.CTkButton(
            input_bar,
            text="◉ MIC",
            width=76,
            height=40,
            fg_color="#0d3326",
            border_width=1,
            border_color=GREEN,
            text_color=GREEN,
            hover_color="#0a271e",
            font=(FONT_UI, 12, "bold"),
            corner_radius=8,
            command=self.toggle_mic,
        )
        self.mic_button.pack(side="left", padx=(10, 0))

        self.power_button = ctk.CTkButton(
            input_bar,
            text="⏻",
            width=46,
            height=40,
            fg_color="#33101a",
            border_width=1,
            border_color=RED,
            text_color=RED,
            hover_color="#260b13",
            font=(FONT_UI, 15, "bold"),
            corner_radius=8,
            command=self.power_down,
        )
        self.power_button.pack(side="left", padx=(10, 0))

        self.status_strip = ctk.CTkLabel(
            right,
            text="◤ SECURE LOCAL MODE // ALL ACTIONS LOGGED LOCALLY ◢",
            font=(FONT_MONO, 9),
            text_color=TEXT_FAINT,
            anchor="w",
        )
        self.status_strip.pack(fill="x", pady=(8, 0))

    def build_body(self):
        body = ctk.CTkFrame(self, fg_color=BG_DEEP, corner_radius=0)
        body.pack(fill="both", expand=True)
        self.build_left_panel(body)
        self.build_right_panel(body)

    # ------------------------------------------------------------ console --
    def _console_text_widget(self):
        """The raw tk.Text inside CTkTextbox (needed for tag styling)."""
        return getattr(self.chat, "_textbox", self.chat)

    def _configure_console_tags(self):
        console = self._console_text_widget()
        try:
            console.configure(
                bg=BG_CONSOLE,
                selectbackground="#12414d",
                insertbackground=CYAN,
                spacing1=2, spacing3=5,
                padx=12, pady=10,
            )
        except Exception:
            pass
        styles = {
            "ts_jarvis": {"foreground": CYAN_DIM, "font": (FONT_MONO, 9)},
            "ts_user": {"foreground": GOLD_DIM, "font": (FONT_MONO, 9)},
            "ts_sys": {"foreground": TEXT_FAINT, "font": (FONT_MONO, 9)},
            "nick_jarvis": {"foreground": CYAN_SOFT, "font": (FONT_MONO, 10, "bold")},
            "nick_user": {"foreground": GOLD, "font": (FONT_MONO, 10, "bold")},
            "nick_sys": {"foreground": TEXT_MUTED, "font": (FONT_MONO, 10)},
            "body_jarvis": {"foreground": "#bfeffb", "font": (FONT_MONO, 12)},
            "body_user": {"foreground": "#f4e3bd", "font": (FONT_MONO, 12)},
            "body_sys": {"foreground": TEXT_MUTED, "font": (FONT_MONO, 11)},
            "rule": {"foreground": "#123245"},
        }
        for tag, config in styles.items():
            try:
                console.tag_configure(tag, **config)
            except Exception:
                pass

    def _stamp(self):
        return dt.datetime.now().strftime("%H:%M:%S")

    def log_line(self, kind, text=None):
        """Enqueue any message onto the ordered mission log."""
        roles = {
            "user": ("ts_user", "YOU    ▸ ", "body_user"),
            "system": ("ts_sys", "SYS    ▸ ", "body_sys"),
            "jarvis": ("ts_jarvis", "JARVIS ▸ ", "body_jarvis"),
        }
        entry = {"kind": kind, "stamp": self._stamp(), "text": str(text or "")}
        if kind in roles:
            entry["tags"] = roles[kind]
        self.console_queue.append(entry)
        self.pump_log()

    def push_rule(self):
        """Thin divider line, part of the ordered stream."""
        console = self._console_text_widget()
        console.insert("end", f"   {'─' * 74}\n", "rule")
        self.chat.see("end")

    def pump_log(self):
        """Single consumer driving the whole mission-log FIFO."""
        if self._closing or self.log_worker_active:
            return
        if not self.console_queue:
            return
        entry = self.console_queue.popleft()

        if entry["kind"] == "rule":
            self.push_rule()
            self.schedule(self.pump_log, delay_ms=60)
            return

        stamp_tag, nick_tag, body_tag = entry["tags"]
        console = self._console_text_widget()
        console.insert("end", f"[{entry['stamp']}] ", stamp_tag)
        console.insert("end", nick_tag, nick_tag)

        if entry["kind"] != "jarvis":
            console.insert("end", f"{entry['text']}\n", body_tag)
            self.chat.see("end")
            self.schedule(self.pump_log, delay_ms=60)
            return

        # JARVIS replies use the typewriter effect.
        console.insert("end", "\n")
        mark_name = f"type_cursor_{self._typing_mark_counter}"
        self._typing_mark_counter += 1
        try:
            console.mark_set(mark_name, "end-1c")
            # Right gravity: insertion happens just before the mark and the
            # mark hops rightward, so chunks accumulate in typed order.
            console.mark_gravity(mark_name, "right")
        except Exception:
            mark_name = None
        job = {"remaining": entry["text"], "mark_name": mark_name}
        self.log_worker_active = True

        def cleanup_and_continue():
            if job["mark_name"]:
                try:
                    console.mark_unset(job["mark_name"])
                except Exception:
                    pass
            console.insert("end", "\n\n")
            self.chat.see("end")
            self.log_worker_active = False
            self.schedule(self.pump_log, delay_ms=140)

        def step():
            if self._closing:
                return
            if not job["remaining"]:
                return cleanup_and_continue()
            chunk = job["remaining"][:3]
            job["remaining"] = job["remaining"][3:]
            try:
                if job["mark_name"]:
                    console.insert(job["mark_name"], chunk, body_tag)
                else:
                    console.insert("end", chunk, body_tag)
                self.chat.see("end")
            except Exception as error:
                print(f"[ui] typewriter step failed: {error}")
                self.log_worker_active = False
                return
            self.schedule(step, delay_ms=15)

        step()

    # ------------------------------------------------------- state machine --
    STATE_STYLES = {
        STATE_IDLE: ("SYSTEM STANDBY", CYAN),
        STATE_LISTENING: ("LISTENING . . . ", "#74ffc9"),
        STATE_THINKING: ("PROCESSING QUERY", "#ff8fe4"),
        STATE_SPEAKING: ("RESPONDING", GOLD),
        STATE_OFFLINE: ("VOICE OFFLINE — TEXT MODE ACTIVE", "#ff7586"),
    }

    def set_state(self, new_state):
        style = self.STATE_STYLES.get(new_state)
        if style is None or new_state == self.hud_state:
            return
        self.hud_state = new_state
        label, color = style
        if not self._closing:
            self.state_label.configure(text=label, text_color=color)

    # ----------------------------------------------------------- responses --
    def on_assistant_output(self, text):
        """Runs on UI thread: every JarvisAssistant.speak() lands here."""
        text = str(text).strip()
        if not text:
            return
        self.log_line("jarvis", text)
        self._turn += 1
        token = self._turn
        self.set_state(STATE_SPEAKING)
        if not self.voice_on:
            estimate = max(1500, min(len(text.split()) * 55 + 900, 6500))
            self.schedule(lambda t=token: self.speech_estimate_done(t), delay_ms=estimate)

    def speech_estimate_done(self, token):
        """Fallback settle when TTS hooks are not available."""
        if token == self._turn and self.hud_state == STATE_SPEAKING:
            self.enter_post_response_state()

    def attach_tts_hooks(self):
        assistant = self.assistant

        def speak_started(_text=None):
            self.schedule(self.set_state, STATE_SPEAKING)

        def speak_ended(_text=None):
            self.schedule(self.tts_bubble_finished)

        try:
            assistant.on_speak_start = speak_started
            assistant.on_speak_end = speak_ended
        except Exception:
            pass

    def tts_bubble_finished(self):
        if self.hud_state == STATE_SPEAKING:
            self._turn += 1
            self.enter_post_response_state()

    def enter_post_response_state(self):
        if self.listener_ok and self.mic_enabled:
            active_listener = getattr(self.assistant, "audio_thread", None)
            if active_listener is not None and active_listener.is_alive():
                self.set_state(STATE_LISTENING)
                return
        self.set_state(STATE_IDLE)

    # ----------------------------------------------------------------- boot --
    def run_boot_sequence(self):
        staged = []
        staged.append(("rule", None))

        def add(kind, text):
            staged.append((kind, text))

        add("system", "BOOT SEQUENCE INITIATED // NEURAL CORE BUILD 3.7")
        add("system", "PERSONALITY MATRIX ................. LOADED")
        add(
            "system",
            "AUDIO ARRAY ........................ ONLINE"
            if self.voice_on
            else "AUDIO ARRAY ........................ STANDBY",
        )
        add(
            "system",
            f"GEMINI AI LINK ..................... {'SECURE' if self.ai_online else 'OFFLINE'}",
        )
        try:
            notes = len(self.assistant.load_notes()) if hasattr(self.assistant, "load_notes") else 0
        except Exception:
            notes = 0
        add("system", f"MEMORY BANKS ....................... {notes} RECORDS")
        add("system", "DESKTOP TELEMETRY CHANNEL .......... SYNCED")
        staged.append(("rule", None))
        add("system", "ALL SYSTEMS NOMINAL. AWAITING YOUR COMMAND.")

        delay = 200
        for kind, text in staged:
            if kind == "rule":
                self.schedule(self.push_rule, delay_ms=delay)
            else:
                self.schedule(lambda k="system", t=text: self.log_line(k, t), delay_ms=delay)
            delay += 110

    # ---------------------------------------------------------- telemetry --
    def _memory_load_percent(self):
        if platform.system() != "Windows" or ctypes is None:
            return None

        class MemoryStatusEx(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        try:
            status = MemoryStatusEx()
            status.dwLength = ctypes.sizeof(MemoryStatusEx)
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return None
            return int(status.dwMemoryLoad)
        except Exception:
            return None

    def _disk_profile(self):
        try:
            import shutil

            total, used, free = shutil.disk_usage(Path.home())
            gb = lambda v: v / (1024 ** 3)
            return {
                "free_pct": free / total * 100.0 if total else 0.0,
                "text": f"{gb(free):.0f} GB FREE",
            }
        except Exception:
            return None

    def _uptime_text(self):
        if platform.system() == "Windows" and ctypes is not None:
            try:
                ms = ctypes.windll.kernel32.GetTickCount64()
                minutes = ms // 60000
                days, rem = divmod(minutes, 1440)
                hours, mins = divmod(rem, 60)
                if days:
                    return f"UPTIME {days}d {hours}h {mins}m"
                return f"UPTIME {hours}h {mins}m"
            except Exception:
                pass
        return f"OS {platform.system()} {platform.release()}"

    def refresh_telemetry(self):
        """Repaint the two neon gauges plus a status footer."""
        if self._closing:
            return
        canvas = self.telemetry
        canvas.delete("all")
        width = max(canvas.winfo_width(), 260)

        mem = self._memory_load_percent()
        disk = self._disk_profile()

        def gauge(y, title, pct, value_text, accent):
            x0, x1 = 14, width - 14
            frac = 0.0 if pct is None else max(0.02, min(pct / 100.0, 1.0))
            canvas.create_line(x0, y, x1, y, fill="#12222f", width=8, capstyle="round")
            bright = mix(accent, "#ffffff", 0.22)
            if frac > 0:
                tip_x = x0 + (x1 - x0) * frac
                canvas.create_line(
                    x0, y, tip_x, y,
                    fill=mix("#12222f", accent, 0.55), width=8, capstyle="round",
                )
                canvas.create_line(
                    x0 + (tip_x - x0) * 0.55, y, tip_x, y,
                    fill=bright, width=8, capstyle="round",
                )
            canvas.create_text(
                x0, y - 16, anchor="w", text=title,
                fill=TEXT_MUTED, font=(FONT_UI, 9, "bold"),
            )
            canvas.create_text(
                x1, y - 16, anchor="e", text=value_text,
                fill=accent, font=(FONT_MONO, 10, "bold"),
            )

        if mem is None:
            gauge(38, "OPERATING SYSTEM", None, platform.release(), CYAN_SOFT)
            machine_line = f"{platform.machine()}"
            canvas.create_text(
                14, 74, anchor="w", text=f"ARCH {machine_line}",
                fill=TEXT_MUTED, font=(FONT_MONO, 10),
            )
        else:
            gauge(38, "MEMORY LOAD", float(mem), f"{mem}%", CYAN)
        if disk:
            gauge(98, "HOME DRIVE", disk["free_pct"], disk["text"], GOLD)

        canvas.create_text(
            14, 148, anchor="w",
            text=self._uptime_text(), fill=TEXT_FAINT, font=(FONT_MONO, 9),
        )
        cores = os.cpu_count() or "?"
        canvas.create_text(
            width - 14, 148, anchor="e",
            text=f"{cores} CORES // HUD ACTIVE", fill=TEXT_FAINT,
            font=(FONT_MONO, 9),
        )

    # ---------------------------------------------------------- animations --
    REACTOR_PRESETS = {
        STATE_IDLE: {"rot": 12, "breath": 3400, "amp": 0.38, "core": CYAN, "ripples": False, "sweeps": False},
        STATE_LISTENING: {"rot": 46, "breath": 1500, "amp": 0.9, "core": "#2ef2d8", "ripples": True, "sweeps": False},
        STATE_THINKING: {"rot": 105, "breath": 2100, "amp": 0.6, "core": MAGENTA, "ripples": False, "sweeps": True},
        STATE_SPEAKING: {"rot": 32, "breath": 1800, "amp": 1.0, "core": GOLD, "ripples": True, "sweeps": False},
        STATE_OFFLINE: {"rot": 5, "breath": 4300, "amp": 0.24, "core": RED, "ripples": False, "sweeps": False},
    }

    def draw_reactor(self, now_ms):
        canvas = self.reactor
        canvas.delete("all")
        preset = self.REACTOR_PRESETS.get(self.hud_state, self.REACTOR_PRESETS[STATE_IDLE])
        c = 148.0
        breath_phase = math.sin(2 * math.pi * (now_ms / preset["breath"]))
        pulse = 0.5 + 0.5 * breath_phase
        intensity = preset["amp"] * (0.42 + 0.58 * pulse)
        core_color = preset["core"]
        if self.hud_state == STATE_OFFLINE:
            intensity *= 0.78 + 0.22 * math.sin(now_ms / 110)

        rot_deg = (now_ms * preset["rot"] / 1000.0) % 360

        # Outer bloom halo: layered strokes fading toward the panel black.
        for layer in range(7):
            factor = 1 - layer / 6.0
            radius = 136 - layer * 4.6
            alpha = (0.03 + 0.10 * factor) * (0.5 + 0.8 * intensity)
            color = fade_to_bg(core_color, alpha)
            canvas.create_oval(
                c - radius, c - radius, c + radius, c + radius,
                outline=color, width=max(int(2 + 5 * factor), 2),
            )

        # Sonar ripples while listening.
        if preset["ripples"] and now_ms >= self._next_ripple_at:
            self._ripples.append({"born": now_ms})
            self._next_ripple_at = now_ms + 720
        surviving = []
        for ripple in self._ripples:
            age = (now_ms - ripple["born"]) / 1500.0
            if age >= 1.0 or self._closing:
                continue
            surviving.append(ripple)
            eased = math.sqrt(age)
            radius = 62 + eased * 92
            alpha = 0.5 * (1 - age)
            color = fade_to_bg(core_color, max(alpha * (0.4 + 0.6 * intensity), 0.06))
            canvas.create_oval(
                c - radius, c - radius, c + radius, c + radius,
                outline=color, width=2,
            )
        self._ripples = surviving

        # Rotating tick ring with shimmering highlights.
        for tick in range(24):
            angle_deg = tick * 15 - rot_deg
            rad = math.radians(angle_deg)
            inner_r, outer_r = 84, 97
            shimmer = 0.5 + 0.5 * math.sin(math.radians(tick * 37) + now_ms / 260)
            alpha = 0.22 + 0.5 * shimmer * (0.4 + 0.6 * intensity)
            color = fade_to_bg(core_color, alpha)
            x1 = c + inner_r * math.cos(rad)
            y1 = c + inner_r * math.sin(rad)
            x2 = c + outer_r * math.cos(rad)
            y2 = c + outer_r * math.sin(rad)
            canvas.create_line(x1, y1, x2, y2, fill=color, width=3, capstyle="round")

        # Structural rings.
        canvas.create_oval(
            c - 108, c - 108, c + 108, c + 108,
            outline=fade_to_bg(core_color, 0.75), width=2,
        )
        canvas.create_oval(
            c - 114, c - 114, c + 114, c + 114,
            outline=fade_to_bg("#2b7ea3", 0.3), width=1, dash=(3, 9),
        )
        canvas.create_oval(
            c - 74, c - 74, c + 74, c + 74,
            outline=fade_to_bg("#135063", 0.55), width=2, dash=(1, 5),
        )

        # Counter-rotating scan sweeps while thinking.
        if preset["sweeps"]:
            span = 82
            box = (c - span, c - span, c + span, c + span)
            sweep_a = (rot_deg * 1.6) % 360
            canvas.create_arc(
                *box, start=sweep_a, extent=120, style="arc",
                outline=fade_to_bg(MAGENTA, 0.85), width=4,
            )
            canvas.create_arc(
                *box, start=(-sweep_a * 0.7 + 150) % 360, extent=80, style="arc",
                outline=fade_to_bg(CYAN, 0.7), width=3,
            )

        # Layered glowing core with a hot white heart.
        core_radius = 20 + 34 * intensity
        for layer in range(6):
            shrink = 1 - 0.115 * layer
            rad = core_radius * shrink
            alpha = 0.13 + 0.145 * layer
            fill = fade_to_bg(mix(core_color, "#ffffff", layer * 0.07), alpha)
            canvas.create_oval(c - rad, c - rad, c + rad, c + rad, fill=fill, outline="")

        hot_radius = 9 + 6 * pulse
        canvas.create_oval(
            c - hot_radius, c - hot_radius, c + hot_radius, c + hot_radius,
            fill=mix(core_color, "#ffffff", 0.72), outline="",
        )
        canvas.create_oval(
            c - hot_radius - 5, c - hot_radius - 5,
            c + hot_radius, c + hot_radius,
            fill="#ffffff", outline="",
        )

    def draw_equalizer(self, now_ms):
        canvas = self.equalizer
        canvas.delete("all")
        width = max(canvas.winfo_width(), 260)
        height = max(canvas.winfo_height(), 70)
        bar_w, gap = 5, 4
        count = int((width - 24) // (bar_w + gap))
        while len(self._eq_values) < count:
            self._eq_values.append(random.uniform(0.05, 0.2))
            self._eq_targets.append(random.uniform(0.05, 0.2))
        while len(self._eq_values) > count:
            self._eq_values.pop()
            self._eq_targets.pop()
        if not count:
            return

        mode_map = {
            STATE_SPEAKING: ("talk", GOLD),
            STATE_LISTENING: ("listen", "#4dffab"),
            STATE_THINKING: ("scan", MAGENTA),
        }
        mode, accent = mode_map.get(self.hud_state, ("idle", CYAN))

        if now_ms >= self._next_eq_target_at:
            self._next_eq_target_at = now_ms + 170
            center_bars = ((width / 2.0 - 12) / (bar_w + gap)) * (
                1 + 0.36 * math.sin(now_ms / 1850)
            )
            sigma = max(count * 0.17, 2.0)
            base = {"talk": 0.92, "listen": 0.78, "scan": 0.5, "idle": 0.12}[mode]
            for i in range(count):
                env = math.exp(-((i - center_bars) ** 2) / (2 * sigma ** 2))
                jitter = 0.4 + random.random() * 0.8
                value = env * base * jitter
                if mode == "idle":
                    value = 0.05 + random.random() * 0.08
                self._eq_targets[i] = max(0.03, min(value, 1.0))

        baseline_y = height - 12
        canvas.create_line(12, baseline_y, width - 12, baseline_y, fill="#101f2c", width=1)
        for i in range(count):
            self._eq_values[i] += (self._eq_targets[i] - self._eq_values[i]) * 0.38
            v = max(self._eq_values[i], 0.02)
            bar_height = v * (height - 22)
            x0 = 12 + i * (bar_w + gap)
            body_alpha = 0.34 + 0.5 * v
            tip_y = baseline_y - bar_height
            canvas.create_line(
                x0, baseline_y, x0, tip_y,
                fill=fade_to_bg(accent, body_alpha), width=bar_w, capstyle="round",
            )
            canvas.create_line(
                x0, tip_y, x0, tip_y + max(bar_height * 0.2, 2),
                fill=mix(accent, "#ffffff", 0.3), width=bar_w, capstyle="round",
            )

    def draw_leds(self, now_ms):
        canvas = self.led_canvas
        canvas.delete("all")
        groups = [
            {"x": 12, "label": "S Y S", "state": "sys"},
            {"x": 68, "label": "L I N K", "state": "link"},
            {"x": 124, "label": "M I C", "state": "mic"},
        ]
        for group in groups:
            x = group["x"]
            if group["state"] == "sys":
                alpha = 0.5 + 0.45 * math.sin(now_ms / 900)
                color = fade_to_bg(CYAN, max(alpha, 0.3))
                glow = fade_to_bg(CYAN, max(alpha - 0.25, 0.08))
            elif group["state"] == "link":
                if self.ai_online:
                    alpha = 0.62 + 0.18 * math.sin(now_ms / 700)
                    color = fade_to_bg(GOLD, alpha)
                    glow = fade_to_bg(GOLD, max(alpha - 0.22, 0.1))
                else:
                    color = "#742634"
                    glow = "#3d1820"
            else:
                if self.listener_ok and self.mic_enabled:
                    alpha = 0.55 + 0.45 * math.sin(now_ms / 480)
                    color = fade_to_bg(GREEN, max(alpha, 0.25))
                    glow = fade_to_bg(GREEN, max(alpha - 0.2, 0.06))
                elif self.hud_state == STATE_OFFLINE:
                    color = "#a12836"
                    glow = "#43161d"
                else:
                    color = "#2c3b48"
                    glow = "#1a2630"
            canvas.create_oval(
                x - 9, 15 - 9, x + 9, 15 + 9, fill=glow, outline="",
            )
            canvas.create_oval(x - 4, 11, x + 4, 19, fill=color, outline="")
            label_color = TEXT_MUTED if color not in ("#2c3b48",) else TEXT_FAINT
            canvas.create_text(
                x, 38, text=group["label"], fill=label_color,
                font=(FONT_UI, 8),
            )

    def update_clock(self):
        if self._closing:
            return
        now = dt.datetime.now()
        self.clock_label.configure(text=now.strftime("%H:%M:%S"))
        weekday = now.strftime("%A").upper()
        self.date_label.configure(text=f"{weekday}  {now:%d %b %Y}")
        self.schedule(self.update_clock, delay_ms=CLOCK_TICK_MS)

    def master_tick(self):
        """Single animation driver: reactor + equalizer + LEDs."""
        if self._closing:
            return
        self.process_events()
        now_ms = time.perf_counter() * 1000.0
        try:
            self.draw_reactor(now_ms)
        except Exception:
            pass
        try:
            self.draw_equalizer(now_ms)
        except Exception:
            pass
        try:
            self.draw_leds(now_ms)
        except Exception:
            pass
        if now_ms >= getattr(self, "_next_telemetry_at", 0):
            self._next_telemetry_at = now_ms + TELEMETRY_TICK_MS
            try:
                self.refresh_telemetry()
            except Exception:
                pass
        self.after(MAIN_TICK_MS, self.master_tick)

    # ------------------------------------------------------------- commands --
    def bind_events(self):
        self.entry.bind("<Return>", lambda _event: self.submit_typed_command())
        self.entry.focus_set()

    def submit_typed_command(self):
        text = self.entry.get().strip()
        if not text:
            return
        self.entry.delete(0, "end")
        self.send_command(text)

    def send_command(self, text):
        """Shared entry point for chips, keyboard input, and actions."""
        text = str(text).strip()
        if not text or self._closing:
            return
        self.log_line("user", text)
        self.set_state(STATE_THINKING)
        threading.Thread(
            target=self._command_thread,
            args=(text,),
            daemon=True,
        ).start()

    def _command_thread(self, text):
        try:
            keep = bool(self.assistant.handle(text))
        except Exception as error:
            print(f"[ui] command crash: {error}")
            keep = True
        self.schedule(self.command_finished, keep)

    def command_finished(self, keep_running):
        if not keep_running:
            self.state_label.configure(text="POWERING DOWN . . .", text_color="#ff7586")
            self.schedule(self.close, delay_ms=1400)
            return
        if self.hud_state == STATE_THINKING:
            self.enter_post_response_state()

    def toggle_mic(self):
        self.mic_enabled = not self.mic_enabled
        if self.mic_enabled:
            self.mic_button.configure(
                text="◉ MIC",
                fg_color="#0d3326",
                border_color=GREEN,
                text_color=GREEN,
                hover_color="#0a271e",
            )
            self.log_line("system", "VOICE CHANNEL ARMED.")
        else:
            self.mic_button.configure(
                text="◌ MUTED",
                fg_color="transparent",
                border_color="#31505f",
                text_color=TEXT_MUTED,
                hover_color="#101c26",
            )
            self.log_line("system", "VOICE CHANNEL MUTED — TYPED COMMANDS ONLY.")

    def power_down(self):
        """Send the farewell command; HUD closes after JARVIS responds."""
        self.send_command("stop")
        self.schedule(self.close, delay_ms=5000)  # hard fallback

    # --------------------------------------------------------------- voice --
    def start_voice_listener(self):
        self.log_line("system", "INITIALIZING AUDIO ARRAY . . .")

        def task():
            try:
                self.assistant.start_audio_listener(
                    self.on_voice_command,
                    self.on_listener_status,
                )
            except Exception as error:
                message = f"AUDIO ARRAY FAULT: {error}"
                self.schedule(self.on_listener_status, message)

        threading.Thread(target=task, daemon=True).start()

    def on_voice_command(self, query):
        """Runs on the audio thread for every recognized phrase."""
        if not query or self._closing:
            return True
        if not self.mic_enabled:
            return True  # stay listening; commands are simply gated off
        keep = True
        try:
            self.log_line("user", query)
            self.set_state(STATE_THINKING)
            keep = bool(self.assistant.handle(query))
        except Exception as error:
            print(f"[ui] voice command crash: {error}")
        if not keep:
            self.schedule(self.command_finished, False)
            # Ending the listener here avoids a second farewell utterance.
            stop_event = getattr(self.assistant, "audio_stop_event", None)
            if stop_event is not None:
                stop_event.set()
        return True

    def on_listener_status(self, message):
        self.schedule(lambda msg=message: self._listener_status_ui(msg))

    def _listener_status_ui(self, message):
        lowered = str(message).lower()
        if "listening" in lowered or "calibrating" in lowered:
            self.listener_ok = True
            if self.hud_state in (STATE_IDLE, STATE_OFFLINE):
                self.set_state(STATE_LISTENING)
        elif any(tag in lowered for tag in ("unavailable", "no microphone", "not installed", "fault")):
            self.listener_ok = False
            self.set_state(STATE_OFFLINE)
            self.mic_button.configure(
                text="◌ MUTED",
                fg_color="transparent",
                border_color="#31505f",
                text_color=TEXT_MUTED,
                hover_color="#101c26",
            )
            self.mic_enabled = False
        self.log_line("system", str(message))

    # -------------------------------------------------------------- lifecycle --
    def close(self):
        if self._closing:
            return
        self._closing = True
        self.state_label.configure(text="SYSTEM OFFLINE", text_color="#ff7586")
        try:
            self.assistant.shutdown()
        except Exception:
            pass
        try:
            super().destroy()
        except Exception:
            pass

    def run(self):
        if not getattr(self, "_built", False):
            self.setup()
        self.mainloop()

    # ------------------------------------------------------- demo responses --
    DEMO_LINES = (
        "Good day, sir. All systems are running at peak efficiency.",
        "Reactor output steady at 3.7 gigajoules. Shall I run a diagnostic sweep?",
        "I have taken the liberty of plotting a course through today's schedule.",
        "Reaction time improved by 12 percent since the last calibration cycle.",
        "Sometimes you have to run before you can walk. Systems nominal, sir.",
    )

    def demo_handle(self, query):
        lowered = query.lower()
        if lowered in {"stop", "exit", "quit", "shutdown"}:
            self.log_line("jarvis", "Powering down the demonstration core. Goodbye, sir.")
            return False
        if lowered in {"time", "what time is it"}:
            reply = f"The time is {dt.datetime.now():%I:%M %p}."
        elif lowered in {"date", "today"}:
            reply = f"Today is {dt.datetime.now():%A, %d %B %Y}."
        elif "joke" in lowered:
            reply = "Why did the AI cross the road? Because that is where the data was cached."
        else:
            reply = random.choice(self.DEMO_LINES)
        self.log_line("jarvis", reply)
        return True


if __name__ == "__main__":
    # Standalone preview of the HUD: python jarvis_sci_fi_ui.py
    SciFiWindow.handle = lambda self, query: self.demo_handle(query)
    hud = SciFiWindow()
    hud.setup(voice_enabled=False, auto_listen=False, boot_sequence=True)
    hud.mainloop()



