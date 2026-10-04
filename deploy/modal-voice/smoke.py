"""Round trip through every configured provider: speak a sentence, transcribe it back.

Reads ~/.savia-voice/voice.json and uses the portal's own VoiceService, so it
checks the same code path the browser reaches. Starts the GPU and costs money.
Pass --save DIR to keep the generated WAV files for listening.
"""
import asyncio
import base64
import json
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from frontend.server.voice import VoiceService  # noqa: E402

SENTENCES = {"es": "No reconozco este cargo de cuarenta y dos mil pesos en mi tarjeta.",
             "pt": "Não reconheço esta cobrança de duzentos reais no meu cartão."}


def wav(pcm: bytes, rate: int) -> bytes:
    return (b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt "
            + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16) + b"data" + struct.pack("<I", len(pcm)) + pcm)


async def main():
    config = json.loads((Path.home() / ".savia-voice" / "voice.json").read_text())
    save = Path(sys.argv[sys.argv.index("--save") + 1]) if "--save" in sys.argv else None
    failed = False
    for provider in config["providers"]:
        service = VoiceService({"providers": [{**provider, "timeout": 600}]})
        for language, sentence in SENTENCES.items():
            if language not in provider.get("voices", {}):
                continue
            try:
                started = time.monotonic()
                rate, stream = await service.speak(sentence, language)
                first, pcm = None, b""
                async for chunk in stream:
                    first = first or time.monotonic() - started
                    pcm += chunk
                pcm = pcm[:len(pcm) - len(pcm) % 2]
                spoken = time.monotonic()
                recording = wav(pcm, rate)
                if save:
                    save.mkdir(parents=True, exist_ok=True)
                    (save / f"{provider['name']}-{language}.wav").write_bytes(recording)
                text = await service.transcribe(base64.b64encode(recording).decode(), language)
                print(f"{provider['name']} {language}: first audio {first:.2f}s, {len(pcm) / 2 / rate:.1f}s of speech "
                      f"in {spoken - started:.2f}s, transcribed in {time.monotonic() - spoken:.2f}s -> {text!r}")
            except Exception as exc:  # noqa: BLE001
                failed = True
                print(f"{provider['name']} {language}: FAILED {type(exc).__name__}: {getattr(exc, 'message', exc)}")
        await service.close()
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    asyncio.run(main())
