"""Single-chat polling and at-most-once delivery, outside the banking authority."""
from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import time
import wave


class DeliveryUncertain(RuntimeError):
    pass


class Journal:
    """No message text/audio, phone number or credentials in the delivery journal."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("CREATE TABLE IF NOT EXISTS messages (id TEXT PRIMARY KEY, state TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS outbound (id TEXT PRIMARY KEY)")
        self.db.commit()
        # A crash during generation/delivery cannot safely authorize a replay.
        self.db.execute("UPDATE messages SET state='uncertain' WHERE state='sending'")
        self.db.execute("UPDATE messages SET state='failed_interrupted' WHERE state='processing'")
        self.db.commit()

    def blocked(self):
        return bool(self.db.execute("SELECT 1 FROM messages WHERE state='uncertain'").fetchone())

    def known(self, identifier):
        identifier = self.digest(identifier)
        return bool(self.db.execute("SELECT 1 FROM messages WHERE id=?", (identifier,)).fetchone()
                    or self.db.execute("SELECT 1 FROM outbound WHERE id=?", (identifier,)).fetchone())

    def set(self, identifier, state):
        identifier = self.digest(identifier)
        self.db.execute("INSERT INTO messages VALUES (?,?) ON CONFLICT(id) DO UPDATE SET state=excluded.state", (identifier, state))
        self.db.commit()

    def sent(self, identifier):
        if not identifier:
            raise DeliveryUncertain("WhatsApp did not return a delivery identifier")
        self.db.execute("INSERT OR IGNORE INTO outbound VALUES (?)", (self.digest(identifier),))
        self.db.commit()

    def acknowledge_uncertain(self):
        """Explicit operator review skips uncertain sends; it never resends them."""
        self.db.execute("UPDATE messages SET state='skipped_by_operator' WHERE state='uncertain'")
        self.db.commit()

    def close(self):
        self.db.close()

    @staticmethod
    def digest(identifier):
        return hashlib.sha256(identifier.encode()).hexdigest()


def normalize_audio(data: bytes, ffmpeg: str) -> bytes:
    if not data or len(data) > 8 * 1024 * 1024:
        raise ValueError("Voice note must be under 8 MiB")
    with tempfile.TemporaryDirectory(prefix="savia-voice-") as directory:
        source, destination = Path(directory) / "input", Path(directory) / "voice.wav"
        source.write_bytes(data)
        result = subprocess.run([ffmpeg, "-nostdin", "-v", "error", "-y", "-i", str(source),
                                 "-t", "31", "-vn", "-ac", "1", "-ar", "24000",
                                 "-c:a", "pcm_s16le", str(destination)],
                                capture_output=True, timeout=30)
        if result.returncode:
            raise ValueError("Voice note could not be decoded")
        with wave.open(str(destination)) as recording:
            if recording.getnframes() > 24000 * 30 or recording.getnframes() < 1:
                raise ValueError("Voice note must be between 0 and 30 seconds")
        return destination.read_bytes()


class Bridge:
    def __init__(self, whatsapp, savia, journal: Journal, *, ffmpeg="ffmpeg", poll_seconds=3):
        self.whatsapp, self.savia, self.journal = whatsapp, savia, journal
        self.ffmpeg, self.poll_seconds = ffmpeg, poll_seconds
        self.started_at = int(time.time())
        self.running = False
        self.busy = False
        self.last_state = "idle"
        self.processed = 0
        self.ready = asyncio.Event()

    async def process(self, message):
        if self.journal.known(message.id) or message.timestamp < self.started_at:
            return
        # In a self-chat, the user's notes are also fromMe. Text is explicitly addressed.
        text = message.body.strip() if message.type == "chat" else ""
        is_voice = message.type in {"ptt", "audio"} and message.has_media
        if not is_voice and not text.casefold().startswith("!savia "):
            self.journal.set(message.id, "ignored")
            return
        self.journal.set(message.id, "processing")
        self.busy, self.last_state = True, "generating"
        attempted_delivery = False
        try:
            if is_voice:
                media = await self.whatsapp.download_media(message.id, message.chat_id)
                if not media.mime_type.startswith("audio/"):
                    raise ValueError("Message is not audio")
                wav = await asyncio.to_thread(normalize_audio, media.data, self.ffmpeg)
                reply = await self.savia.converse(audio_wav=wav)
            else:
                reply = await self.savia.converse(message=text[7:].strip())
            self.journal.set(message.id, "sending")
            self.last_state = "sending"
            attempted_delivery = True
            receipt = await self.whatsapp.send_text("Savia · demostración ficticia\n" + reply.text)
            self.journal.sent(receipt.id)
            if reply.voice_turns:
                receipt = await self.whatsapp.send_voice_note(reply.voice_turns[-1].wav, "audio/wav")
                self.journal.sent(receipt.id)
            self.journal.set(message.id, "delivered")
            self.processed += 1
            self.last_state = "delivered_not_playback_verified"
        except asyncio.CancelledError:
            self.journal.set(message.id, "uncertain" if attempted_delivery else "failed_interrupted")
            self.last_state, self.running = "operator_review_required" if attempted_delivery else "generation_failed", False
            raise
        except Exception:
            # Any transport failure may hide a successful WhatsApp send; never blindly retry.
            self.journal.set(message.id, "uncertain" if attempted_delivery else "failed")
            self.last_state, self.running = "operator_review_required" if attempted_delivery else "generation_failed", False
        finally:
            self.busy = False

    async def run(self):
        if self.journal.blocked():
            raise DeliveryUncertain("Review uncertain delivery before starting")
        self.started_at = int(time.time())
        # Baseline only this configured chat; exclude all pre-existing history.
        try:
            for message in await self.whatsapp.list_messages(after_timestamp=0):
                self.journal.set(message.id, "baseline")
        except Exception:
            self.last_state = "startup_failed"
            self.ready.set()
            return
        self.running, self.last_state = True, "listening"
        self.ready.set()
        while self.running:
            try:
                messages = await self.whatsapp.list_messages(after_timestamp=self.started_at)
                for message in sorted(messages, key=lambda item: (item.timestamp, item.id)):
                    if not self.running:
                        break
                    await self.process(message)
            except asyncio.CancelledError:
                raise
            except Exception:
                self.last_state, self.running = "poll_failed", False
            if self.running:
                await asyncio.sleep(self.poll_seconds)

    def stop(self):
        self.running = False
