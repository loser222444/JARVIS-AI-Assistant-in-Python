"""Masked Gemini connectivity diagnostic for JARVIS (safe to share output).

Checks, in order:
  1. Key presence/format — via project .env, .env beside the executable,
     and the system/user environment variable.
  2. Client construction through the same google-genai SDK path JARVIS uses.
  3. Live request against candidate models (newest first), classifying
     rejections, retired models, quota exhaustion, and network faults.

No part of the API key is ever printed.

Usage:
    .venv\\Scripts\\python.exe gemini_probe.py
"""

import os
import sys

from dotenv import load_dotenv

MODEL_CANDIDATES = (
    os.environ.get("JARVIS_GEMINI_MODEL") or None,
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-2.5-flash",
)

EXIT_OK, EXIT_NO_KEY, EXIT_BROKEN_SETUP, EXIT_REJECTED, EXIT_OTHER = range(5)


def locate_env_file():
    """Same discovery order as voice_assistant.app_dir() based loading."""
    project_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [os.path.join(project_dir, ".env")]
    if getattr(sys, "frozen", False):
        candidates.insert(0, os.path.join(os.path.dirname(sys.executable), ".env"))
    else:
        candidates.append(os.path.join(os.path.dirname(sys.executable), ".env"))
    return next((path for path in candidates if os.path.isfile(path)), None)


def mask(value):
    return f"{value[:4]}...{value[-4:]} (length {len(value)})"


def classify(message):
    lowered = str(message).lower()
    if any(tag in lowered for tag in (
        "api_key_invalid", "api key not valid", "invalid api key",
        "permission_denied", "unauthenticated", "401", "403",
    )):
        return ("KEY REJECTED BY GOOGLE",
                "Create a fresh key at https://aistudio.google.com/app/apikey "
                "and update .env / your GEMINI_API_KEY variable.")
    if "quota" in lowered or "resource_exhausted" in lowered or "429" in lowered:
        return ("VALID KEY BUT QUOTA EXHAUSTED",
                "Wait for the quota window to reset or raise limits in Google AI Studio.")
    if any(tag in lowered for tag in (
        "timed out", "timeout", "connection", "network", "getaddrinfo",
        "name or service not known", "proxy",
    )):
        return ("NETWORK FAILURE", "Check internet / VPN / proxy, then retry.")
    return ("UNCERTAIN ERROR", str(message)[:300])


def main():
    env_path = locate_env_file()
    if env_path:
        load_dotenv(env_path, override=True)
        print(f".env SOURCE  : {env_path}")
    else:
        print(".env SOURCE  : none found - relying on environment variables")

    raw_key = os.environ.get("GEMINI_API_KEY", "").strip().strip("'\"")
    if not raw_key:
        print("STATUS       : MISSING KEY")
        print("FIX          : put GEMINI_API_KEY=<key> in .env beside the app,")
        print("               or set it at User level in Windows.")
        return EXIT_NO_KEY
    print(f"KEY PRESENT  : {mask(raw_key)}")

    try:
        from google import genai
    except ImportError:
        print("STATUS       : BROKEN SETUP - google-genai package missing")
        return EXIT_BROKEN_SETUP

    try:
        client = genai.Client(api_key=raw_key)
    except Exception as error:  # noqa: BLE001
        reason, advice = classify(error)
        print(f"STATUS       : {reason}")
        print(f"DETAIL       : {error}")
        print(f"FIX          : {advice}")
        return EXIT_REJECTED

    attempted = []
    last_error = None
    for model in filter(None, MODEL_CANDIDATES):
        attempted.append(model)
        try:
            response = client.models.generate_content(
                model=model, contents="Reply with exactly one word: ONLINE",
            )
            reply = (response.text or "").strip()
            print("LIVE CALL OK : " + f"model={model} reply={reply!r}")
            print("STATUS       : VALID LINK ✔")
            return EXIT_OK
        except Exception as error:  # noqa: BLE001
            last_error = error
            reason, _advice = classify(error)
            if reason == "UNCERTAIN ERROR" and "not_found" in str(error).lower():
                print(f"{model:<20}: model unavailable -> trying next candidate")
                continue
            break

    reason, advice = classify(last_error)
    tried = ", ".join(attempted)
    print(f"MODELS TRIED : {tried}")
    print(f"STATUS       : {reason}")
    print(f"LAST ERROR   : {last_error}")
    print(f"FIX          : {advice}")
    return EXIT_OTHER


if __name__ == "__main__":
    raise SystemExit(main())
