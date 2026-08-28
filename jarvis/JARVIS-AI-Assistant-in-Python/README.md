## Run the assistant

From `D:\python`, activate the virtual environment and run the script from its project directory:

```powershell
& D:\python\jarvis\JARVIS-AI-Assistant-in-Python\.venv\Scripts\Activate.ps1
Set-Location D:\python\jarvis\JARVIS-AI-Assistant-in-Python
python -m pip install -r requirements.txt
python voice_assistant.py
```

This opens the cinematic sci-fi HUD (CustomTkinter): animated arc-reactor core, neon glow palettes, sonar ripples while listening, scan sweeps while thinking, live memory/disk telemetry, a typewriter mission log, and quick-command chips. Voice recognition runs automatically when a microphone is available; typed commands always work. Use `python voice_assistant.py --terminal` for the console interface instead, or run `python jarvis_sci_fi_ui.py` to preview the HUD in standalone demo mode.

The script is located in `JARVIS-AI-Assistant-in-Python`, so `python voice_assistant.py` will fail if it is run directly from `D:\python`.

## Troubleshooting

### `[ui] sci-fi HUD unavailable ... falling back to terminal mode` or `The sci-fi HUD requires the 'customtkinter' package`

JARVIS was launched with an interpreter that does not have CustomTkinter (for example the global Python instead of the project `.venv`). Launch it with the virtual environment:

```powershell
& D:\python\jarvis\JARVIS-AI-Assistant-in-Python\.venv\Scripts\Activate.ps1
Set-Location D:\python\jarvis\JARVIS-AI-Assistant-in-Python
python -m pip install -r requirements.txt
python voice_assistant.py
```

In VS Code, press `Ctrl+Shift+P` → **Python: Select Interpreter** and choose the `.venv` one (`D:\python\jarvis\JARVIS-AI-Assistant-in-Python\.venv\Scripts\python.exe`) before running or debugging. JARVIS never hard-crashes because of this: without the HUD package it automatically runs in terminal mode.

### "I could not reach Gemini" / `Gemini is not configured`

Run the masked diagnostic first — it classifies missing keys, rejected keys, retired models, quota exhaustion and offline states without ever printing your key:

```powershell
python gemini_probe.py
```

Key facts:

- The key lives in `.env` next to the app (or a User-level Windows variable `GEMINI_API_KEY`). Both work for scripts **and** `JARVIS.exe`.
- Ask questions explicitly with `ask <question>`; unknown phrases also route to Gemini.
- `ask_gemini` automatically walks models newest-first (override via `JARVIS_GEMINI_MODEL`) and retries transient blips once; specific spoken errors mean specific causes:
  - *"access was rejected"* → replace the key
  - *"quota is exhausted"* → wait or raise limits
  - *"lost the connection… mid-request"* → retry shortly; usually transient VPN/Wi-Fi

## Capabilities

JARVIS now includes a futuristic desktop interface, terminal HUD, voice recognition with typed fallback, text-to-speech, local notes, safe calculator expressions, system and disk status, web search, YouTube, Google, GitHub, Stack Overflow, Spotify, Calendar, Maps, News, Reddit, Email, Drive, Translate and Wikipedia launchers, weather search, Explorer, Notepad, Paint, Task Manager and Calculator controls, mouse and keyboard automation, media keys and keyboard shortcuts, screenshots, common folder access, Windows PC locking, music playback, jokes, and graceful shutdown commands.

## Complete command list

### General

- `help`, `commands`, `what can you do`
- `hello`, `hi`, `hey jarvis`
- `stop`, `stop listening`, `stop assistant`, `exit`, `quit`, `shutdown`

### Information and AI

- `time`, `what time is it`, `current time`
- `date`, `what is the date`, `today`
- `status`, `system status`, `system check`, `system info`
- `disk space`, `free space`, `storage`
- `calculate <expression>` or `what is <numeric expression>`
- `ask <question>`

### Notes

- `remember <text>`
- `read notes`, `show notes`, `my notes`
- `note count`, `notes count`, `how many notes`

### Web and media

- `search <words>`
- `search youtube <words>`
- `weather` or `weather in <place>`
- `open google`, `open browser`, `google`
- `open youtube`, `youtube`
- `open github`, `github`
- `open stackoverflow`, `stackoverflow`, `open stack overflow`, `stack overflow`
- `open spotify`, `spotify`
- `open calendar`, `calendar`
- `open maps`, `maps`, `open google maps`
- `open news`, `news`
- `open reddit`, `reddit`
- `open email`, `email`, `open gmail`, `gmail`
- `open drive`, `drive`, `google drive`
- `open translate`, `translate`, `google translate`
- `open wikipedia`, `wikipedia`
- `play music`
- `joke`
- `who are you`, `your name`

### Applications and folders

- `open explorer`, `open home`
- `open notepad`
- `open calculator`
- `open paint`
- `open task manager`
- `open command prompt`
- `open settings`
- `open control panel`
- `open desktop`, `open documents`, `open downloads`, `open music`
- `open path <path>`

### Desktop control

- `mouse position`, `where is my mouse`, `cursor position`
- `move mouse to <X> <Y>`
- `click`, `left click`, `double click`, `right click`
- `type <text>`
- `press <key>`: `enter`, `escape`, `tab`, `space`, `backspace`, `up`, `down`, `left`, `right`, `volumeup`, `volumedown`, or `volumemute`
- `volume up`, `volume down`, `mute`, `volume mute`
- `scroll <number>` from `-20` to `20`, excluding `0`
- `copy`, `paste`, `cut`, `undo`, `save`, `select all`
- `show desktop`, `minimize windows`
- `hotkey ctrl+c`, `hotkey ctrl+v`, `hotkey ctrl+x`, `hotkey ctrl+a`, `hotkey ctrl+z`, `hotkey ctrl+s`, `hotkey alt+tab`, `hotkey win+d`
- `screenshot`, `take screenshot`

### File operations

- `list files` or `list files <path>`
- `file info <path>`
- `create folder <path>`
- `move file <source> to <destination>`

### PC control

- `lock pc`, `lock computer`, `lock my pc`

JARVIS does not execute arbitrary shell commands, delete files, or power off the computer.

To verify the installation without using the microphone:

```powershell
python voice_assistant.py --self-test
```

To verify the sci-fi HUD renders and animates correctly without touching the microphone or network:

```powershell
python test_ui_smoke.py
```

Set `JARVIS_MUSIC_DIR` before launching if your music is stored somewhere other than your user Music folder.

For continuous microphone mode, run:

```powershell
python voice_assistant.py --continuous
```

JARVIS reads `daily_tasks.txt` at startup and speaks its contents. Edit that file to set the daily task list, or set `JARVIS_DAILY_TASKS_FILE` to use another local file. On Windows, launching JARVIS registers it to start in continuous microphone mode at the next user login.

## Gemini AI

Create a Gemini API key in Google AI Studio, then set it only in your local environment. Do not paste the key into `voice_assistant.py` or commit it to Git:

```powershell
$env:GEMINI_API_KEY = "paste-your-key-here"
python voice_assistant.py
```

Ask Gemini from the interface with:

```text
ask explain how Python decorators work
```

JARVIS uses the `gemini-2.5-flash` model. Without `GEMINI_API_KEY`, all local commands continue to work and the `ask` command explains how to configure it.

run assistant
Set-Location D:\python\JARVIS-AI-Assistant-in-Python
& D:\python\JARVIS-AI-Assistant-in-Python\.venv\Scripts\Activate.ps1
python voice_assistant.py
