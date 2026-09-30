"""Public, opaque reference for a locally unresolved demo action."""
from __future__ import annotations

import hashlib
import re


_ACTION_UUID = re.compile(r"^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$")
_LEGACY_ACTION = re.compile(r"^[a-f0-9]{32}$")


def review_reference(action_id: str | None) -> str | None:
    """Derive a stable public code only from a durable random action ID."""
    if not isinstance(action_id, str) or not (
            _ACTION_UUID.fullmatch(action_id) or _LEGACY_ACTION.fullmatch(action_id)):
        return None
    digest = hashlib.sha256(("savia-demo-review-v1:" + action_id).encode("ascii")).hexdigest()
    return "rev_" + digest[:24]
