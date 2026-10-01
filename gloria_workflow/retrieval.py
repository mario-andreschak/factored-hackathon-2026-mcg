"""Bounded application-owned retrieval from reviewed synthetic policy chunks."""
from __future__ import annotations

from pathlib import Path
import re


_ROOT = Path(__file__).resolve().parents[1] / "resources" / "policies"
_FILES = {
    "TRANSACTION_DISPUTE": "transaction_dispute_policy.md",
    "TRANSACTION_INQUIRY": "transaction_dispute_policy.md",
    "COMPLAINT_STATUS": "complaint_handling_policy.md",
    "HUMAN_REQUEST": "human_handoff_policy.md",
}


def retrieve_policy(intent, *, human_required=False, max_chars=7000):
    names = [_FILES.get(intent)]
    if human_required:
        names.append("human_handoff_policy.md")
    chunks, remaining = [], max_chars
    for name in dict.fromkeys(n for n in names if n):
        text = (_ROOT / name).read_text(encoding="utf-8")
        parts = re.split(r"<!-- chunk_id:\s*([A-Za-z0-9_-]+)\s*-->", text)
        for i in range(1, len(parts), 2):
            body = parts[i+1].split("\n##", 1)[0].strip()
            # Narrative policy is explanatory. Private risk thresholds and
            # technical authorization internals do not enter customer prompts.
            sentences = re.split(r"(?<=[.!?])\s+", body)
            body = " ".join(s for s in sentences if not re.search(r"owner|snapshot|target|risk_data|fraud_score|umbral|conteo|intern[ao]s?|host|revalida", s, re.I))
            if body and len(body) <= remaining:
                chunks.append({"chunk_id": parts[i], "text": body})
                remaining -= len(body)
    return chunks
