"""Create the auth secret if missing, deploy, and save the private voice config.

Writes ~/.savia-voice/voice.json, outside Git. Point the portal at it with
SAVIA_VOICE_CONFIG_FILE, or copy its content under "voice" in frontend.json.
Set OPENROUTER_API_KEY when running this to add OpenRouter as the fallback
that covers the GPU's cold start.
"""
import json
import os
import re
import secrets
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PRIVATE = Path.home() / ".savia-voice"
APP = "savia-voice"


def main():
    import modal
    PRIVATE.mkdir(exist_ok=True)
    token_path, config_path = PRIVATE / "token", PRIVATE / "voice.json"
    if not token_path.exists():
        token = secrets.token_urlsafe(48)
        modal.Secret.objects.create(APP + "-auth", {"SAVIA_VOICE_TOKEN": token}, allow_existing=False)
        token_path.write_text(token)
    result = subprocess.run([sys.executable, "-X", "utf8", "-m", "modal", "deploy", str(ROOT / "app.py")],
                            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
                            env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    if result.returncode:
        sys.exit(result.returncode)
    endpoints = list(dict.fromkeys(re.findall(r"https://[A-Za-z0-9.-]+\.modal\.run", re.sub(r"\s+", "", result.stdout))))
    if len(endpoints) != 1:
        sys.exit(f"Expected one endpoint in deploy output, found {endpoints}")
    providers = [{"name": "savia-gpu", "kind": "openai", "base_url": endpoints[0] + "/v1",
                  "api_key": token_path.read_text().strip(), "stt_model": "whisper-large-v3",
                  "tts_model": "kokoro", "voices": {"es": "ef_dora", "pt": "pf_dora"},
                  # Short on purpose: a cold GPU hands the turn to the fallback and keeps starting.
                  "sample_rate": 24000, "timeout": 12}]
    if key := os.environ.get("OPENROUTER_API_KEY"):
        providers.append({"name": "openrouter", "kind": "openrouter", "api_key": key,
                          "stt_model": "openai/whisper-large-v3", "tts_model": "google/gemini-3.8-flash-lite-tts",
                          "voices": {"es": "Kore", "pt": "Kore"}, "sample_rate": 24000, "timeout": 45})
    config_path.write_text(json.dumps({"providers": providers}, indent=2))
    print("deployed:", endpoints[0])
    print("private voice config (contains the token):", config_path)


if __name__ == "__main__":
    main()
