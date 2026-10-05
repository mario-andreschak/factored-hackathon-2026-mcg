"""Supervise the public RC with persistent fresh fictional state only."""
from pathlib import Path
import json
import os
import secrets
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
PRIVATE = Path("/data/rc-private")


def main():
    os.umask(0o077)
    if os.getuid() == 0:
        Path("/data").mkdir(exist_ok=True)
        os.chown("/data", 1000, 1000)
        os.setgid(1000)
        os.setuid(1000)
    env = dict(os.environ)
    origin = env["RC_PUBLIC_ORIGIN"]
    if not (PRIVATE / "fixture.json").is_file():
        subprocess.run([sys.executable, str(ROOT / "deploy/rc/run.py"), "--private-dir", str(PRIVATE), "--prepare"], check=True)
    policy = PRIVATE / "gateway-policy.json"
    if not policy.exists():
        policy.write_text(json.dumps({"gate": secrets.token_urlsafe(48), "cookie": secrets.token_urlsafe(48)}))
        policy.chmod(0o600)
    values = json.loads(policy.read_text())
    env.update(AVATAR_ACCESS_GATE_TOKEN=values["gate"], RC_COOKIE_SECRET=values["cookie"],
               AVATAR_HOST="127.0.0.1", AVATAR_PORT="43941", AVATAR_PUBLIC_ORIGIN=origin,
               SAVIA_UPSTREAM="http://127.0.0.1:43900", SAVIA_PUBLIC_ORIGIN=origin,
               AVATAR_VOICE_PROVIDER="openrouter-native", AVATAR_NATIVE_READ_BRIDGE="readonly",
               AVATAR_BACKGROUND_ASR="openrouter",
               NODE_ENV="production", RC_DEMO_CODE=env.get("RC_DEMO_CODE", "SAVIA-2026"))
    commands = [
        [sys.executable, str(ROOT / "deploy/rc/run.py"), "--private-dir", str(PRIVATE),
         "--provider", "openrouter", "--public-origin", origin],
        ["node", str(ROOT / "avatar/server/index.mjs")],
        ["node", str(ROOT / "deploy/rc/public-gateway.mjs")],
    ]
    children = []
    stopping = False
    def stop(*_):
        nonlocal stopping
        stopping = True
        for child in children:
            if child.poll() is None:
                child.terminate()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        for command in commands:
            children.append(subprocess.Popen(command, cwd=ROOT, env=env))
        while not stopping:
            failed = next((child for child in children if child.poll() is not None), None)
            if failed:
                raise RuntimeError(f"RC child exited ({failed.returncode})")
            time.sleep(.5)
    finally:
        stop()
        for child in children:
            try:
                child.wait(timeout=8)
            except subprocess.TimeoutExpired:
                child.kill()


if __name__ == "__main__":
    main()
