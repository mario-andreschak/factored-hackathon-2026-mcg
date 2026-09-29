from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    mode: Literal["delegated", "synthetic-demo", "operator-test"] = "delegated"
    data_dir: Path
    state_db: Path
    service_token: str = Field(min_length=32, repr=False)
    issuer: str = "flujo-banking-runtime"
    audience: str = "banking-mcp"
    public_keys: dict[str, str] = Field(default_factory=dict, repr=False)
    principal_customers: dict[str, str] = Field(default_factory=dict, repr=False)
    demo_customer: str | None = None
    approved_customers: frozenset[str] = Field(default_factory=frozenset, repr=False)
    source_env: Path | None = None
    # An operator attests when the SANDBOX report ledger became complete. This
    # never represents bank-wide historical reporting coverage.
    sandbox_report_coverage_start: int | None = Field(default=None, ge=1)
    max_active_reads: int = Field(default=8, ge=1, le=32)
    max_queued_reads: int = Field(default=512, ge=1, le=1024)
    http_hosts: list[str] = Field(default_factory=lambda: ["127.0.0.1:*", "localhost:*"])

    @field_validator("http_hosts")
    @classmethod
    def fixed_hostnames(cls, values):
        import re
        if not values or any(not re.fullmatch(r"[A-Za-z0-9.-]+:(?:\*|[0-9]{1,5})", v) for v in values):
            raise ValueError("http_hosts requires explicit hostnames with a port or :*")
        return values

    @model_validator(mode="after")
    def validate_mode(self):
        if not self.data_dir.is_absolute() or not self.state_db.is_absolute():
            raise ValueError("data_dir and state_db must be absolute")
        if self.mode == "delegated":
            if not self.public_keys or not self.principal_customers or self.demo_customer or self.approved_customers:
                raise ValueError("delegated mode requires keys and a private subject mapping")
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
            from cryptography.hazmat.primitives.serialization import load_pem_public_key
            for value in self.public_keys.values():
                if not isinstance(load_pem_public_key(value.encode()), Ed25519PublicKey):
                    raise ValueError("only Ed25519 public keys are supported")
        elif self.mode == "operator-test":
            # Explicit private operator configuration, never a missing-auth fallback.
            # Administrators approve only organizer-synthetic or generated fixture customers.
            if (not self.approved_customers or self.demo_customer or self.public_keys or self.principal_customers
                or any(not 1 <= len(c) <= 128 or c != c.strip() for c in self.approved_customers)):
                raise ValueError("operator-test requires only an explicit approved customer allowlist")
        else:
            # A demo cannot point at the real dataset or accept caller-selected customers.
            marker = self.data_dir / "SYNTHETIC_BANKING_DEMO.json"
            if self.source_env or self.approved_customers or not self.demo_customer or not marker.is_file():
                raise ValueError("synthetic-demo requires an explicitly generated fixture")
            if json.loads(marker.read_text(encoding="utf-8")) != {
                "synthetic": True, "customer": self.demo_customer
            }:
                raise ValueError("synthetic demo marker mismatch")
        return self


def load_config(path: str | Path) -> Config:
    return Config.model_validate_json(Path(path).read_text(encoding="utf-8"))
