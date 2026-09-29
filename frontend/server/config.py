from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    state_dir: Path
    static_dir: Path
    demo_code: str = "2026"
    secure_cookie: bool = False
    public_origin: str | None = None
    session_seconds: int = 8 * 60 * 60
    profiles: dict = field(default_factory=dict, repr=False)
    chat: dict = field(default_factory=dict, repr=False)

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
            demo_code=os.environ.get("BANKING_DEMO_CODE", str(config.get("demo_code", "2026"))),
            secure_cookie=os.environ.get("BANKING_COOKIE_SECURE", "0") == "1",
            public_origin=os.environ.get("BANKING_PUBLIC_ORIGIN") or config.get("public_origin"),
            profiles=config.get("profiles", {}),
            chat=config.get("chat", {}),
        )
