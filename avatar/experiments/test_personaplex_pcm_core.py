"""Local stdlib tests only: no PersonaPlex weights, microphone, or cloud calls."""

import struct
from itertools import repeat
import unittest

from personaplex_pcm_core import (
    ContinuousDriver, FRAME_BYTES, FRAME_SAMPLES, MAX_BUFFER_FRAMES,
    OUTPUT_HEADER, Pcm24Framer, PublicResultQueue, pack_output,
    pcm16_to_float, unpack_output,
)


class PcmTests(unittest.TestCase):
    def test_byte_and_frame_partitions_preserve_every_sample(self):
        samples = [((n * 199) % 65536) - 32768 for n in range(FRAME_SAMPLES * 8)]
        encoded = struct.pack(f"<{len(samples)}h", *samples)
        for partitions in ((1,), (4097,), (73, 8192, 3, 512, 777)):
            with self.subTest(partitions=partitions):
                framer = Pcm24Framer()
                frames = []
                offset = 0
                index = 0
                while offset < len(encoded):
                    size = partitions[index % len(partitions)]
                    frames.extend(framer.push(encoded[offset:offset + size]))
                    offset += size
                    index += 1
                framer.finish()
                self.assertEqual(b"".join(frames), encoded)
                self.assertEqual(len(frames), 8)
                self.assertEqual(framer.sample_index, len(samples))

    def test_float_endpoints_are_pcm16_le(self):
        frame = struct.pack("<1920h", -32768, 32767, *([0] * (FRAME_SAMPLES - 2)))
        decoded = pcm16_to_float(frame)
        self.assertEqual(decoded[:2], (-1.0, 32767 / 32768))
        self.assertEqual(len(decoded), FRAME_SAMPLES)
        with self.assertRaises(ValueError):
            pcm16_to_float(frame[:-1])

    def test_truncation_and_backlog_fail_instead_of_inventing_samples(self):
        framer = Pcm24Framer()
        framer.push(b"\x00")
        with self.assertRaises(ValueError):
            framer.finish()
        framer.discard()
        framer.finish()
        with self.assertRaises(BufferError):
            framer.push(bytes(FRAME_BYTES * MAX_BUFFER_FRAMES + 1))
        self.assertEqual(framer.sample_index, 0)

    def test_output_generation_and_clock_roundtrip(self):
        pcm = b"\x00\x80\xff\x7f"
        packet = pack_output(5, 1920 * 123, pcm)
        output = unpack_output(packet)
        self.assertEqual((output.generation, output.sample_index, output.pcm),
                         (5, 1920 * 123, pcm))
        for malformed in (packet[:-1], packet[:OUTPUT_HEADER.size], b"\x01" + packet[1:]):
            with self.subTest(packet=malformed), self.assertRaises(ValueError):
                unpack_output(malformed)


class ResultTests(unittest.TestCase):
    def test_free_generation_barge_in_changes_presentation_generation_once(self):
        queue = PublicResultQueue("epoch")
        self.assertIsNone(queue.next_token(user_active=True))
        self.assertEqual(queue.generation, 1)
        self.assertIsNone(queue.next_token(user_active=True))
        self.assertEqual(queue.generation, 1)
        self.assertIsNone(queue.next_token(user_active=False))
        self.assertIsNone(queue.next_token(user_active=True))
        self.assertEqual(queue.generation, 2)

    def test_epoch_deduplication_and_explicit_pad_schedule(self):
        queue = PublicResultQueue("account-a/session-1")
        self.assertFalse(queue.admit("stale", "account-a/session-0", [10]))
        self.assertTrue(queue.admit("read-1", queue.epoch, [41, 3, 3, 0, 99]))
        self.assertFalse(queue.admit("read-1", queue.epoch, [52]))
        self.assertEqual([queue.next_token(user_active=False) for _ in range(6)],
                         [41, 3, 3, 0, 99, None])
        self.assertEqual(queue.generation, 0)

    def test_user_onset_cancels_only_active_speech_and_defers_pending_result(self):
        queue = PublicResultQueue("epoch")
        queue.admit("read-1", "epoch", [40, 41, 42])
        queue.admit("read-2", "epoch", [80, 81])
        self.assertEqual(queue.next_token(user_active=False), 40)
        self.assertIsNone(queue.next_token(user_active=True))
        self.assertEqual(queue.generation, 1)
        self.assertIsNone(queue.next_token(user_active=True))
        self.assertEqual(queue.generation, 1)
        self.assertIsNone(queue.next_token(user_active=False, allow_speech=False))
        self.assertEqual(queue.next_token(user_active=False), 80)
        self.assertEqual(queue.next_token(user_active=False), 81)
        self.assertIsNone(queue.next_token(user_active=False))
        # Canceled spoken result is not silently admitted a second time.
        self.assertFalse(queue.admit("read-1", "epoch", [40, 41, 42]))

    def test_pending_cancellation_and_validation(self):
        queue = PublicResultQueue("epoch")
        queue.admit("read-1", "epoch", [40])
        queue.cancel("read-1")
        self.assertIsNone(queue.next_token(user_active=False))
        self.assertEqual(queue.generation, 0)
        for tokens in ([], [1], [2], [-1], [32_000], [True], [4] * 257):
            with self.subTest(tokens=tokens), self.assertRaises(ValueError):
                queue.admit("invalid", "epoch", tokens)
        with self.assertRaises(ValueError):
            queue.admit("unbounded-generator", "epoch", repeat(4))
        for index in range(4):
            queue.admit(f"pending-{index}", "epoch", [10])
        with self.assertRaises(BufferError):
            queue.admit("overflow", "epoch", [10])

    def test_continuous_clock_runs_during_mute_and_barge_in_without_reset(self):
        queue = PublicResultQueue("epoch")
        queue.admit("public-read", "epoch", [40, 3, 41])
        calls = []

        def fake_step(frame, text_token):
            calls.append((frame, text_token))
            return len(calls)

        driver = ContinuousDriver(queue, fake_step)
        silence = bytes(FRAME_BYTES)
        self.assertEqual(driver.feed(silence, allow_speech=False), [1])
        self.assertEqual(driver.feed(silence), [2])
        self.assertEqual(driver.feed(silence, user_active=True), [3])
        self.assertEqual(driver.feed(silence, allow_speech=False), [4])
        self.assertEqual(driver.feed(silence), [5])
        self.assertEqual([token for _, token in calls], [None, 40, None, None, None])
        self.assertEqual(driver.frames, 5)
        self.assertEqual(driver.framer.sample_index, 5 * FRAME_SAMPLES)
        self.assertTrue(all(not any(frame) for frame, _ in calls))
        driver.close()
        self.assertFalse(queue.admit("late-read", "epoch", [40]))
        with self.assertRaises(RuntimeError):
            driver.feed(silence)


if __name__ == "__main__":
    unittest.main()
