"""Live GUI smoke test for the JARVIS sci-fi HUD (no microphone or network).

Runs the CustomTkinter window against the offline DemoAssistant for a few
seconds, exercises the command pipeline, state transitions, mic toggle,
listener-status handling, and telemetry repaint, then closes cleanly.

Usage:
    .venv\\Scripts\\python.exe test_ui_smoke.py
"""

import sys

import jarvis_sci_fi_ui as hud_mod


def run_smoke():
    # Force the demo core so no TTS / mic / network is touched.
    hud_mod._ASSISTANT_CLASS_CACHE = hud_mod.DemoAssistant

    win = hud_mod.SciFiWindow()
    try:
        win.setup(voice_enabled=False, auto_listen=False, boot_sequence=True)

        # Exercise the command pipeline and all state transitions.
        win.log_line("system", "SMOKE TEST START")
        win.send_command("status")
        win.set_state(hud_mod.STATE_THINKING)
        win.after(600, lambda: win.log_line("jarvis", "Smoke-test reply from the neural core."))
        win.after(1200, lambda: win.refresh_telemetry())
        win.after(1800, lambda: win.toggle_mic())   # mute
        win.after(2300, lambda: win.toggle_mic())   # unmute
        win.after(2800, lambda: win.on_listener_status("listening for wake word"))
        win.after(3300, win.enter_post_response_state)
        win.after(4000, lambda: print(f"[smoke] final state={win.hud_state!r}"))
        win.after(4500, win.close)

        print("[smoke] entering mainloop ...")
        win.mainloop()
        print("[smoke] mainloop exited cleanly -> PASS")
    except Exception as exc:  # noqa: BLE001
        import traceback

        traceback.print_exc()
        try:
            win.destroy()
        except Exception:
            pass
        raise SystemExit(f"[smoke] FAIL: {exc}") from exc


if __name__ == "__main__":
    sys.exit(run_smoke() or 0)
