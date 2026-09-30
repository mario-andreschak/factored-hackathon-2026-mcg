"""One pipeline writer per output root; stale locks require operator recovery."""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

LOCK_FILENAME = ".pipeline-writer.lock"


@contextmanager
def writer_lock(out_dir: Path | str):
    """Acquire atomically on Windows/Linux and keep the lock for the whole run.

    An interrupted process may leave this file behind. We deliberately never
    guess whether its PID is still a writer: only an operator who has confirmed
    that every writer stopped may remove a stale lock and restart the pipeline.
    """
    root = Path(out_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    path = root / LOCK_FILENAME
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise RuntimeError(
            f"pipeline output is locked by another writer: {path}. "
            "Confirm that the writer has stopped before removing a stale lock."
        ) from None

    identity = os.fstat(descriptor)
    try:
        # fdopen owns the descriptor even if writing metadata or the run fails.
        with os.fdopen(descriptor, "w", encoding="utf-8") as lock:
            json.dump({"pid": os.getpid(),
                       "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}, lock)
            lock.write("\n")
            lock.flush()
            yield path
    finally:
        # Never remove a replacement lock created after an operator removed ours.
        # The descriptor is closed before unlinking, as required on Windows.
        try:
            current = path.stat()
        except FileNotFoundError:
            pass
        else:
            if (current.st_dev, current.st_ino) == (identity.st_dev, identity.st_ino):
                path.unlink()
