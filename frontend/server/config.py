from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit


PROFILE_IDS = frozenset({"colombia", "mexico", "argentina"})
SYNTHETIC_MARKER = "team_synthetic_fixture"


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    state_dir: Path
    static_dir: Path
    demo_code: str = ""
    auth_mode: str = "demo"
    invites: dict[str, str] = field(default_factory=dict, repr=False)
    expected_snapshot: dict[str, str] = field(default_factory=dict, repr=False)
    secure_cookie: bool = False
    public_origin: str | None = None
    session_seconds: int = 8 * 60 * 60
    profiles: dict = field(default_factory=dict, repr=False)
    chat: dict = field(default_factory=dict, repr=False)

    def __post_init__(self):
        if not isinstance(self.auth_mode, str) or self.auth_mode not in {"demo", "invite"}:
            raise ValueError("Invalid banking authentication mode")
        if self.auth_mode == "demo":
            return
        if not isinstance(self.invites, dict) or not 1 <= len(self.invites) <= len(PROFILE_IDS):
            raise ValueError("Invite mode requires hashed visitor invites")
        targets = []
        for digest, profile_id in self.invites.items():
            if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
                raise ValueError("Invite codes must be stored as SHA-256 digests")
            if not isinstance(profile_id, str) or profile_id not in PROFILE_IDS:
                raise ValueError("Invite target must be an approved synthetic profile")
            targets.append(profile_id)
        if len(set(targets)) != len(targets) or not isinstance(self.profiles, dict) or set(self.profiles) != set(targets):
            raise ValueError("Each invite requires one unique explicit profile binding")
        for profile in self.profiles.values():
            if not isinstance(profile, dict) or not isinstance(profile.get("customer_id"), str) or not 1 <= len(profile["customer_id"]) <= 128:
                raise ValueError("Invite profiles require explicit customer bindings")
        if len({profile["customer_id"] for profile in self.profiles.values()}) != len(self.profiles):
            raise ValueError("Invite profiles must bind distinct synthetic customers")
        expected = self.expected_snapshot
        if (not isinstance(expected, dict) or set(expected) != {"build_id", "source_fingerprint", "kind"}
                or not isinstance(expected["build_id"], str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,96}", expected["build_id"])
                or not isinstance(expected["source_fingerprint"], str)
                or not re.fullmatch(r"[a-f0-9]{12,64}", expected["source_fingerprint"])
                or expected["kind"] != SYNTHETIC_MARKER):
            raise ValueError("Invite mode requires a pinned synthetic snapshot")
        if not isinstance(self.public_origin, str):
            raise ValueError("Invite mode requires an exact public origin")
        origin = urlsplit(self.public_origin)
        try:
            port = origin.port
        except ValueError as exc:
            raise ValueError("Invalid invite public origin") from exc
        if (origin.scheme not in {"http", "https"} or not origin.hostname or origin.username or origin.password
                or origin.path or origin.query or origin.fragment or self.public_origin.endswith("/") or port == 0):
            raise ValueError("Invite mode requires an exact public origin")
        loopback = origin.hostname in {"localhost", "127.0.0.1", "::1"}
        if (origin.scheme == "http" and not loopback) or (not loopback and not self.secure_cookie):
            raise ValueError("Non-loopback invite mode requires HTTPS and secure cookies")
        if self.chat:
            raise ValueError("Invite mode requires a separate synthetic chat deployment")

    def auth_fingerprint(self) -> str:
        policy = {"auth_mode": self.auth_mode}
        # Retire pre-migration portal cookies before a new host bank binding can
        # be admitted. Generic language graph/name changes do not rotate bank identity.
        if self.chat.get("mode") == "host-direct-mcp/v1":
            policy["bank_host_mode"] = "host-direct-mcp/v1"
            policy["bank_namespace"] = self.chat.get("namespace")
            policy["bank_ledger_generation"] = self.chat.get("ledger_generation")
        if self.auth_mode == "invite":
            policy.update(invites=self.invites, profiles=self.profiles, expected_snapshot=self.expected_snapshot,
                          public_origin=self.public_origin, secure_cookie=self.secure_cookie)
        else:
            # A changed private demo code retires sessions issued under it.
            policy["demo_code_digest"] = hashlib.sha256(self.demo_code.encode()).hexdigest()
        return hashlib.sha256(json.dumps(policy, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    @classmethod
    def from_env(cls) -> "Settings":
        config = {}
        if filename := os.environ.get("BANKING_CONFIG_FILE"):
            config = json.loads(Path(filename).read_text(encoding="utf-8-sig"))
            if not isinstance(config, dict):
                raise ValueError("Banking configuration must be an object")
        frontend_dir = Path(__file__).resolve().parents[1]
        return cls(
            data_dir=Path(os.environ.get("BANKING_DATA_DIR", str(frontend_dir.parent / "data"))).resolve(),
            state_dir=Path(os.environ.get("BANKING_STATE_DIR", str(frontend_dir.parent / "data" / "frontend-state"))).resolve(),
            static_dir=Path(os.environ.get("BANKING_STATIC_DIR", str(frontend_dir / "dist"))).resolve(),
            demo_code=os.environ.get("BANKING_DEMO_CODE", str(config.get("demo_code", ""))),
            auth_mode=config.get("auth_mode", "demo"),
            invites=config.get("invites", {}),
            expected_snapshot=config.get("expected_snapshot", {}),
            secure_cookie=os.environ.get("BANKING_COOKIE_SECURE", "0") == "1",
            public_origin=os.environ.get("BANKING_PUBLIC_ORIGIN") or config.get("public_origin"),
            profiles=config.get("profiles", {}),
            chat=config.get("chat", {}),
        )
