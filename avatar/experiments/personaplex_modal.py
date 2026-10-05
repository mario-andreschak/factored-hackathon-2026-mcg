"""Bounded, ephemeral PersonaPlex audition. --plan is local; --execute spends compute.

No persistent app, endpoint, volume, schedule or named secret is created.
Only NVIDIA's public bundled test audio is accepted as input.
"""
from __future__ import annotations

import argparse
import io
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request
import wave

SOURCE_REPO = "https://github.com/NVIDIA/personaplex.git"
SOURCE_REVISION = "3428dfd95309a7f3c84fd93259ded0f810d1ff91"
MODEL_REPO = "nvidia/personaplex-7b-v1"
MODEL_REVISION = "fdaf4090a61cb315c138a1faee287ffd6c716309"
MODEL_FILES = (
    "config.json", "model.safetensors", "tokenizer-e351c8d8-checkpoint125.safetensors",
    "tokenizer_spm_32k_3.model", "voices.tgz",
)
GPU = "A100-80GB"
FUNCTION_SECONDS = 600
STARTUP_SECONDS = 60
CPU_LIMIT = 4
MEMORY_LIMIT_GIB = 64
AUDIO_SECONDS = 20
VOICE = "NATM1.pt"
PROMPT = "You enjoy having a good conversation. Your name is Moss, a gentle ancient turtle. Speak calmly and warmly, using short thoughtful phrases. Help the user find one clear next step."

# Standard Function rates, verified on https://modal.com/pricing, 2026-10-01.
GPU_RATE = 0.000694
CPU_RATE = 0.0000131
MEMORY_RATE = 0.00000222


def plan() -> dict:
    per_second = GPU_RATE + CPU_LIMIT * CPU_RATE + MEMORY_LIMIT_GIB * MEMORY_RATE
    return {
        "status": "prepared_not_dispatched", "source": SOURCE_REPO,
        "source_revision": SOURCE_REVISION, "model": MODEL_REPO,
        "model_revision": MODEL_REVISION, "gpu": GPU,
        "timeout_seconds": FUNCTION_SECONDS, "startup_timeout_seconds": STARTUP_SECONDS,
        "max_containers": 1, "retries": 0, "cpu_limit": CPU_LIMIT,
        "memory_limit_gib": MEMORY_LIMIT_GIB, "public_audio_seconds": AUDIO_SECONDS,
        "maximum_runtime_estimate_usd": round(per_second * FUNCTION_SECONDS, 4),
        "runtime_startup_idle_estimate_usd": round(per_second * (FUNCTION_SECONDS + STARTUP_SECONDS + 2), 4),
        "total_target_usd": 1.00,
        "cost_note": "CPU image building is separate; the $1 total is an estimate, not a provider billing cap. No region premium or nonpreemptible option.",
        "credential": "existing HF_TOKEN or existing Hugging Face cache, injected through an ephemeral Modal Secret",
        "prerequisite": "Account must already have permission for the gated NVIDIA model. The script never accepts its license.",
        "persistent_service": False,
        "function_transport": "source", "container_python": "3.11",
        "client_python": f"{sys.version_info.major}.{sys.version_info.minor}",
    }


def diagnostic(error: Exception, stage: str) -> dict:
    """Recognize fixed failure categories without forwarding messages or URLs."""
    allowed_classes = {"InvalidError", "RemoteError", "AuthenticationError", "AuthError", "ExecutionError",
                       "FunctionTimeoutError", "TimeoutError", "TimeoutExpired", "GatedRepoError",
                       "HfHubHTTPError", "RepositoryNotFoundError", "EntryNotFoundError", "RuntimeError",
                       "ModuleNotFoundError", "FileNotFoundError", "CalledProcessError", "OSError", "ValueError"}
    name = type(error).__name__
    text = str(error).lower()
    if "serialized" in text and "python" in text and ("compatible" in text or "version" in text):
        code = "client_python_incompatible"
    elif name == "GatedRepoError" or "gated repo" in text:
        code = "model_access_denied"
    elif name in {"TimeoutError", "TimeoutExpired", "FunctionTimeoutError"}:
        code = "deadline_exceeded"
    elif "out of memory" in text:
        code = "gpu_memory_exhausted"
    elif name == "ModuleNotFoundError" or "modulenotfounderror" in text:
        code = "dependency_missing"
    elif "image" in text and ("build" in text or "building" in text):
        code = "image_build_failed"
    elif name in {"AuthenticationError", "AuthError"}:
        code = "modal_auth_unavailable"
    else:
        code = "audition_failed"
    return {"stage": stage, "failure_code": code, "error_class": name if name in allowed_classes else "UnclassifiedError"}


def write_failure(value: dict) -> Path:
    directory = Path(__file__).resolve().parent.parent / ".local" / "personaplex-smoke"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"failure-{time.time_ns()}.json"
    path.write_text(json.dumps(value, indent=2), encoding="utf8")
    return path


def existing_token() -> str:
    value = os.environ.get("HF_TOKEN", "").strip()
    if not value:
        try:
            value = (Path.home() / ".cache" / "huggingface" / "token").read_text().strip()
        except OSError:
            pass
    if not value or len(value) > 32768 or any(char.isspace() for char in value):
        raise RuntimeError("An existing Hugging Face read token is required.")
    return value


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, url):
        return None


def check_access(token: str) -> int:
    # Never follow a signed redirect or send this credential to another host.
    url = f"https://huggingface.co/{MODEL_REPO}/resolve/{MODEL_REVISION}/model.safetensors"
    request = urllib.request.Request(url, method="HEAD", headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=15) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code
    except (urllib.error.URLError, TimeoutError):
        return 0


def access_allowed(status: int) -> bool:
    return status == 200 or status in (302, 303, 307, 308)


def extract_voice(archive: Path, destination: Path) -> None:
    """Read exactly one known regular member; never perform archive extraction."""
    with tarfile.open(archive, "r:gz") as source:
        matches = [member for member in source.getmembers() if not PurePosixPath(member.name).is_absolute() and PurePosixPath(member.name).parts == ("voices", VOICE)]
        if len(matches) != 1:
            raise RuntimeError("The fixed voice embedding is unavailable or ambiguous.")
        member = matches[0]
        if not member.isfile() or member.size > 64 * 1024 * 1024:
            raise RuntimeError("The fixed voice embedding is invalid.")
        handle = source.extractfile(member)
        if handle is None:
            raise RuntimeError("The fixed voice embedding is unavailable.")
        value = handle.read(64 * 1024 * 1024 + 1)
        if len(value) != member.size:
            raise RuntimeError("The fixed voice embedding is incomplete.")
        destination.write_bytes(value)


def audio_profile(value: bytes) -> dict:
    if len(value) > 3 * 1024 * 1024:
        raise RuntimeError("The audition returned oversized audio.")
    try:
        with wave.open(io.BytesIO(value), "rb") as audio:
            seconds = audio.getnframes() / audio.getframerate()
            if audio.getnchannels() != 1 or audio.getframerate() != 24000 or not 0 < seconds <= AUDIO_SECONDS + 0.2:
                raise RuntimeError("The audition returned an unexpected audio profile.")
            return {"sample_rate": 24000, "channels": 1, "seconds": round(seconds, 3), "bytes": len(value)}
    except (wave.Error, EOFError, ZeroDivisionError) as error:
        raise RuntimeError("The audition returned invalid audio.") from error


PINNED_RUNNER = r'''
import json, os, runpy, sys, torch, huggingface_hub
original_download = huggingface_hub.hf_hub_download
def pinned_download(repo_id, filename, **options):
    if repo_id != "nvidia/personaplex-7b-v1":
        raise RuntimeError("Only the fixed model is allowed")
    options.pop("revision", None)
    options.pop("token", None)
    options.pop("local_files_only", None)
    return original_download(repo_id, filename, revision="fdaf4090a61cb315c138a1faee287ffd6c716309", token=os.environ["HF_TOKEN"], local_files_only=True, **options)
huggingface_hub.hf_hub_download = pinned_download
sys.argv = ["moshi.offline", *sys.argv[1:]]
runpy.run_module("moshi.offline", run_name="__main__")
with open("/tmp/personaplex-smoke/gpu.json", "w") as output:
    json.dump({"name":torch.cuda.get_device_name(0), "peak_allocated_bytes":torch.cuda.max_memory_allocated(0)}, output)
'''


def gpu_smoke() -> dict:
    """One input only. All weight loading and inference occur inside the 600s timeout."""
    from huggingface_hub import hf_hub_download

    started = time.monotonic()
    stage = "weights"
    try:
        if not os.environ.get("HF_TOKEN"):
            return {"status": "failed", "stage": "access", "reason": "HF_TOKEN was not injected."}
        assets = {
            filename: hf_hub_download(MODEL_REPO, filename, revision=MODEL_REVISION, token=os.environ["HF_TOKEN"])
            for filename in MODEL_FILES
        }
        downloaded = time.monotonic()
        work = Path("/tmp/personaplex-smoke")
        work.mkdir(exist_ok=False)
        voice_dir = work / "voices"
        voice_dir.mkdir()
        extract_voice(Path(assets["voices.tgz"]), voice_dir / VOICE)
        stage = "public_audio"
        # No caller audio/path/URL: fixed public fixture at the pinned source revision.
        subprocess.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i",
            "/opt/personaplex/assets/test/input_assistant.wav", "-t", str(AUDIO_SECONDS),
            "-ar", "24000", "-ac", "1", "-c:a", "pcm_s16le", str(work / "input.wav"),
        ], check=True, capture_output=True, timeout=20)
        stage = "inference"
        command = [
            sys.executable, "-c", PINNED_RUNNER,
            "--input-wav", str(work / "input.wav"), "--voice-prompt", VOICE,
            "--voice-prompt-dir", str(voice_dir), "--text-prompt", PROMPT,
            "--moshi-weight", assets["model.safetensors"],
            "--mimi-weight", assets["tokenizer-e351c8d8-checkpoint125.safetensors"],
            "--tokenizer", assets["tokenizer_spm_32k_3.model"],
            "--hf-repo", MODEL_REPO, "--seed", "42424242", "--device", "cuda",
            "--output-wav", str(work / "response.wav"), "--output-text", str(work / "text.json"),
        ]
        environment = {**os.environ, "HF_HUB_OFFLINE": "1", "HF_HUB_DISABLE_PROGRESS_BARS": "1"}
        # Capture diagnostics instead of exposing credentials or arbitrary upstream
        # error messages through Modal logs. Only fixed failure stages are returned.
        completed = subprocess.run(command, cwd="/opt/personaplex", env=environment, capture_output=True, timeout=360)
        if completed.returncode:
            details = diagnostic(RuntimeError(completed.stderr.decode("utf8", errors="replace")), stage)
            return {"status": "failed", **details, "reason": "The fixed NVIDIA offline entrypoint failed."}
        stage = "output"
        # sphn may write IEEE-float WAV. Normalize its fixed output to ordinary
        # PCM16 WAV so validation and browser playback have one exact profile.
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(work / "response.wav"),
                        "-t", str(AUDIO_SECONDS), "-ar", "24000", "-ac", "1", "-c:a", "pcm_s16le", str(work / "audition.wav")],
                       check=True, capture_output=True, timeout=20)
        response_audio = (work / "audition.wav").read_bytes()
        profile = audio_profile(response_audio)
        text = (work / "text.json").read_text()
        if len(text) > 64000 or not isinstance(json.loads(text), list):
            raise RuntimeError("The audition returned invalid text.")
        return {
            "status": "completed", "audio": response_audio, "text": text,
            "report": {"source_revision": SOURCE_REVISION, "model_revision": MODEL_REVISION,
                       "download_seconds": round(downloaded - started, 2),
                       "load_and_inference_seconds": round(time.monotonic() - downloaded, 2),
                       "audio": profile, "gpu": json.loads((work / "gpu.json").read_text()),
                       "banking_access": False, "browser_barge_in_verified": False},
        }
    except Exception as error:
        return {"status": "failed", **diagnostic(error, stage), "reason": "The bounded audition could not complete. Check model access, resources and pinned dependencies."}


def build_image(*, copy_source=False):
    """Lazy pinned image definition shared with separately bounded experiments."""
    import modal
    return (
        modal.Image.debian_slim(python_version="3.11")
        .apt_install("git", "libopus-dev", "libportaudio2", "ffmpeg")
        .pip_install(
            "torch==2.4.1", "numpy==1.26.4", "safetensors==0.4.5",
            "huggingface-hub==0.24.7", "einops==0.7.0", "sentencepiece==0.2.0",
            "sounddevice==0.5.0", "sphn==0.1.4", "aiohttp==3.10.11",
        )
        .run_commands(
            "git init /opt/personaplex",
            f"git -C /opt/personaplex remote add origin {SOURCE_REPO}",
            f"git -C /opt/personaplex fetch --depth 1 origin {SOURCE_REVISION}",
            f"git -C /opt/personaplex checkout --detach {SOURCE_REVISION}",
            "python -m pip install --no-deps /opt/personaplex/moshi",
        )
        .env({"HF_HUB_ETAG_TIMEOUT": "15", "HF_HUB_DOWNLOAD_TIMEOUT": "30", "HF_HUB_DISABLE_PROGRESS_BARS": "1"})
        .add_local_python_source("personaplex_modal", copy=copy_source)
    )


def build_app(token: str):
    # Importing or planning this file never creates a cloud app or reads a token.
    import modal
    if sys.version_info < (3, 10):
        raise RuntimeError("The Modal client needs Python 3.10 or newer.")
    if gpu_smoke.__module__ != "personaplex_modal":
        raise RuntimeError("Run the source-backed experiment through its documented script entrypoint.")
    image = build_image()
    app = modal.App("elsewhere-personaplex-audition")
    ephemeral_secret = modal.Secret.from_dict({"HF_TOKEN": token})
    function = app.function(
        image=image, gpu=GPU, cpu=(2, CPU_LIMIT), memory=(32768, MEMORY_LIMIT_GIB * 1024),
        timeout=FUNCTION_SECONDS, startup_timeout=STARTUP_SECONDS,
        max_containers=1, min_containers=0, buffer_containers=0, scaledown_window=2,
        retries=0, single_use_containers=True, serialized=False, include_source=True,
        secrets=[ephemeral_secret],
    )(gpu_smoke)
    return app, function


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--plan", action="store_true", help="Print the local plan; no credentials/network/cloud access.")
    mode.add_argument("--check-access", action="store_true", help="Authenticated HEAD at the fixed HF model; print status only, no download.")
    mode.add_argument("--execute", action="store_true", help="Run one bounded GPU audition after existing model permission is verified.")
    options = parser.parse_args(argv)
    if not options.check_access and not options.execute:
        print(json.dumps(plan(), indent=2))
        return 0
    try:
        token = existing_token()
    except RuntimeError:
        print(json.dumps({"status": "blocked", "reason": "An existing Hugging Face read token is required."}))
        return 2
    status = check_access(token)
    if options.check_access or not access_allowed(status):
        print(json.dumps({"model_access_status": status, "existing_access_allowed": access_allowed(status), "cloud_dispatched": False}))
        return 0 if access_allowed(status) else 2
    stage = "app_definition"
    try:
        app, function = build_app(token)
        # Ephemeral run, connected to this process, with one function call only.
        # No deploy, serve, schedule, retries or persistent named secret.
        stage = "app_start"
        with app.run(detach=False):
            stage = "gpu_input"
            job = function.spawn()
            try:
                # A client wall-clock deadline also bounds provider preemption
                # rescheduling, independent of the per-input runtime timeout.
                result = job.get(timeout=FUNCTION_SECONDS + STARTUP_SECONDS + 15)
            finally:
                try: job.cancel(terminate_containers=True)
                except Exception: pass
        if result.get("status") != "completed":
            public = {key: result[key] for key in ("status", "stage", "reason", "failure_code", "error_class") if key in result}
            path = write_failure(public)
            print(json.dumps({**public, "report": str(path)}))
            return 1
        stage = "local_output"
        profile = audio_profile(result["audio"])
        destination = Path(__file__).resolve().parent.parent / ".local" / "personaplex-smoke" / time.strftime("%Y%m%d-%H%M%S")
        destination.mkdir(parents=True, exist_ok=False)
        (destination / "response.wav").write_bytes(result["audio"])
        (destination / "text.json").write_text(result["text"], encoding="utf8")
        (destination / "report.json").write_text(json.dumps(result["report"], indent=2), encoding="utf8")
        print(json.dumps({"status": "completed", "output_directory": str(destination), "audio": profile, "persistent_service": False}))
        return 0
    except Exception as error:
        public = {"status": "failed", **diagnostic(error, stage), "reason": "The ephemeral audition failed. No persistent service was requested."}
        try: public["report"] = str(write_failure(public))
        except OSError: pass
        print(json.dumps(public))
        return 1


if __name__ == "__main__":
    # Canonical module identity lets Modal load source on Python 3.11 even when
    # the existing local client runs another supported Python version.
    from importlib import import_module
    raise SystemExit(import_module("personaplex_modal").main())
