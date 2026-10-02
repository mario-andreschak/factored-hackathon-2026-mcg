"""Project documentation and organizer reference history, with honest dates."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from io import BytesIO
import importlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


EXCLUDED_PARTS = {".git", ".codex", ".history", "node_modules", "venv", ".venv", "private", "data", "banking-data", "dist", "build", "coverage"}


def _is_doc(path: str) -> bool:
    normalized = path.replace("\\", "/")
    parts = {part.lower() for part in normalized.split("/")}
    name = Path(normalized).name.lower()
    if parts & EXCLUDED_PARTS or any(word in name for word in ("credentials", "secret", "token", ".env")):
        return False
    # The original dictionary's credential page is explicitly excluded even if
    # someone later moves it out of private/. Only the redacted copy is read.
    if "data_dictionary" in name and "redacted" not in name:
        return False
    suffix = Path(normalized).suffix.lower()
    if suffix in {".md", ".rst", ".pdf"}:
        return True
    if suffix in {".yml", ".yaml"} and normalized.startswith(".github/workflows/"):
        return True
    if suffix == ".txt" and ("docs" in parts or "notes" in parts):
        return True
    return suffix == ".json" and "docs" in parts and ("aggregate" in name or "report" in name)


def _git(repo: Path, args: list[str], binary: bool = False):
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, timeout=120, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace").strip()[:500])
    return result.stdout if binary else result.stdout.decode("utf-8", errors="replace")


def _utc(value: str) -> str:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _pdf_reader():
    try:
        return importlib.import_module("pypdf").PdfReader
    except ImportError:
        # Codex desktop ships pypdf, while the user's default interpreter may
        # not. This is optional discovery; no packages are installed.
        candidates = []
        configured = os.environ.get("HISTORY_PYTHON_SITE_PACKAGES")
        if configured:
            candidates.append(Path(configured))
        if os.name == "nt":
            candidates.extend(Path.home().glob(".cache/codex-runtimes/*/dependencies/python/Lib/site-packages"))
        for candidate in candidates:
            if (candidate / "pypdf").is_dir():
                sys.path.insert(0, str(candidate))
                try:
                    return importlib.import_module("pypdf").PdfReader
                except ImportError:
                    continue
    return None


def _extract(raw: bytes, path: str, pdf_reader) -> tuple[str, dict]:
    if Path(path).suffix.lower() != ".pdf":
        return raw.decode("utf-8-sig", errors="replace"), {"format": Path(path).suffix.lower().lstrip(".")}
    if pdf_reader:
        reader = pdf_reader(BytesIO(raw))
        pages = [page.extract_text() or "" for page in reader.pages]
        text = "\n\n".join(f"[Page {number + 1}]\n{page}" for number, page in enumerate(pages))
        return text, {"format": "pdf", "pageCount": len(pages), "extraction": "pypdf",
                      "imageOnlyPages": [number + 1 for number, text in enumerate(pages) if not text.strip()]}
    if shutil.which("pdftotext"):
        result = subprocess.run(["pdftotext", "-", "-"], input=raw, capture_output=True, timeout=90)
        if result.returncode == 0:
            return result.stdout.decode("utf-8", errors="replace"), {"format": "pdf", "extraction": "pdftotext"}
    return "", {"format": "pdf", "extraction": "unavailable"}


def _title(text: str, path: str) -> str:
    heading = re.search(r"(?m)^#\s+(.+)$", text)
    return heading.group(1).strip() if heading else Path(path).name


def _tags(path: str) -> list[str]:
    lower = path.lower()
    tags = ["documentation"]
    if "hackathon" in lower or "kickoff" in lower or "datathon" in lower:
        tags.append("hackathon")
    if "/reference/" in lower.replace("\\", "/"):
        tags.append("reference")
    if "factored ai" in lower or "kickoff" in lower:
        tags.append("rules")
    if "audit" in lower or "review" in lower or "report" in lower:
        tags.append("evidence")
    if lower.startswith(".github/workflows/"):
        tags.extend(["ci", "automation", "workflow"])
    return tags


def collect(repo: Path, config: dict) -> dict:
    """Read docs across project branches, retaining full text of each revision.

    Unchanged document content is deduplicated by path and SHA-256. Untracked
    documents use filesystem modification time, explicitly labelled as such.
    """
    repo = Path(repo)
    if not config.get("docs_enabled", True):
        return {"events": [], "status": "ok", "notes": ["Documentation collection disabled."], "documents": [], "stats": {}}
    events = []
    documents: dict[str, dict] = {}
    notes = []
    failures = []
    hashes: set[tuple[str, str]] = set()
    pdf_reader = _pdf_reader()
    ref_types = [] if config.get("github_include_internal_refs", False) else ["refs/heads", "refs/remotes", "refs/tags"]
    repository = config.get("github_repository") or config.get("github_repo")
    if not repository:
        try:
            remote = _git(repo, ["remote", "get-url", "origin"]).strip()
            match = re.search(r"(?:https?://|git@)[^/:]+(?::|/)([^/]+/[^/]+?)(?:\.git)?/?$", remote)
            repository = match.group(1) if match else None
        except (RuntimeError, OSError, subprocess.TimeoutExpired):
            pass
    hostname = config.get("github_hostname", "github.com")

    def add_document(path: str, raw: bytes, timestamp: str, actor: str, sha: str | None,
                     timestamp_basis: str, subject: str = ""):
        digest = hashlib.sha256(raw).hexdigest()
        key = path, digest
        if key in hashes:
            return
        hashes.add(key)
        try:
            text, metadata = _extract(raw, path, pdf_reader)
        except Exception as exc:
            failures.append({"path": path, "revision": sha, "error": f"PDF extraction: {type(exc).__name__}: {exc}"})
            text, metadata = "", {"format": "pdf", "extraction": "failed"}
        if metadata.get("extraction") == "unavailable":
            failures.append({"path": path, "revision": sha, "error": "PDF extraction unavailable; install pypdf or use the bundled runtime."})
        metadata.update({"path": path, "sha256": digest, "bytes": len(raw), "commit": sha,
                         "timestampBasis": timestamp_basis, "commitSubject": subject})
        url = f"https://{hostname}/{repository}/blob/{sha}/{path}" if repository and sha else ""
        kind = "document_revision" if sha else "document_snapshot"
        event = {"id": f"docs:{path}:{digest}", "timestamp": _utc(timestamp), "source": "docs", "kind": kind,
                 "title": _title(text, path), "body": text, "actor": actor, "url": url,
                 "threadId": "docs:" + path, "tags": _tags(path), "metadata": metadata}
        events.append(event)
        current = documents.setdefault(path, {"path": path, "title": event["title"], "revisions": [], "tags": event["tags"]})
        current["revisions"].append({"eventId": event["id"], "timestamp": event["timestamp"], "sha256": digest,
                                     "commit": sha, "timestampBasis": timestamp_basis})
        if not current.get("latestAt") or event["timestamp"] >= current["latestAt"]:
            current.update({"latestAt": event["timestamp"], "latestEventId": event["id"], "title": event["title"]})

    try:
        refs = [line for line in _git(repo, ["for-each-ref", "--format=%(refname)", *ref_types]).splitlines() if line]
        patterns = ["*.md", "*.rst", "*.pdf", "notes/*.txt", "docs/*.txt", "docs/*AGGREGATE*.json", "docs/*report*.json", ".github/workflows/*.yml", ".github/workflows/*.yaml"]
        fmt = "%x1e%H%x1f%cI%x1f%an%x1f%s%x1e"
        log = _git(repo, ["log", "--reverse", "--format=" + fmt, "--name-only", *(refs or ["HEAD"]), "--", *patterns])
        headers = list(re.finditer(r"\x1e([a-f0-9]{40,64})\x1f([^\x1f]+)\x1f([^\x1f]+)\x1f([^\x1e]*)\x1e", log))
        if config.get("docs_include_history", True):
            for index, match in enumerate(headers):
                sha, timestamp, actor, subject = match.groups()
                end = headers[index + 1].start() if index + 1 < len(headers) else len(log)
                paths = [line.strip().strip('"') for line in log[match.end():end].splitlines() if line.strip()]
                for path in paths:
                    if not _is_doc(path):
                        continue
                    try:
                        raw = _git(repo, ["show", f"{sha}:{path}"], binary=True)
                    except RuntimeError:
                        # A deletion has no content revision. Its Git commit is
                        # still collected independently by github.py.
                        continue
                    add_document(path, raw, timestamp, actor, sha, "git_committer_time", subject)
        current_paths = _git(repo, ["ls-files", "--cached", "--others", "--exclude-standard", "-z"]).split("\0")
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
        failures.append({"path": "local-git", "error": str(exc)})
        current_paths = [str(path.relative_to(repo)) for path in repo.rglob("*") if path.is_file() and _is_doc(str(path.relative_to(repo)))]

    for path in current_paths:
        if not path or not _is_doc(path):
            continue
        file = repo / path
        if not file.is_file():
            continue
        try:
            raw = file.read_bytes()
            if (path, hashlib.sha256(raw).hexdigest()) in hashes:
                documents[path]["presentInWorkingTree"] = True
                continue
            # A working-tree edit cannot inherit the old commit's date. A
            # matching tracked blob uses Git time, otherwise explicitly mtime.
            tracked = _git(repo, ["log", "-1", "--format=%H%x1f%cI%x1f%an%x1f%s", "HEAD", "--", path]).strip()
            pieces = tracked.split("\x1f", 3) if tracked else []
            if len(pieces) == 4 and _git(repo, ["show", f"{pieces[0]}:{path}"], binary=True) == raw:
                add_document(path, raw, pieces[1], pieces[2], pieces[0], "git_committer_time", pieces[3])
            else:
                timestamp = datetime.fromtimestamp(file.stat().st_mtime, timezone.utc).isoformat()
                add_document(path, raw, timestamp, "Working tree", None, "filesystem_mtime")
            documents[path]["presentInWorkingTree"] = True
        except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
            failures.append({"path": path, "error": str(exc)})
    for document in documents.values():
        document["revisions"].sort(key=lambda item: (item["timestamp"], item["eventId"]))
        document["firstObservedAt"] = document["revisions"][0]["timestamp"]
    notes.append("Documentation dates come from Git committer timestamps; working-tree edits/untracked documents use explicitly labelled filesystem mtime.")
    notes.append("Identical document content is deduplicated per path; current bodies and all distinct Git revisions are retained.")
    notes.append("Private directories, credential files and the unredacted original data dictionary are excluded.")
    image_only = [event["metadata"]["path"] for event in events if event["metadata"].get("imageOnlyPages")]
    if image_only:
        notes.append("PDF text extraction omits image-only page content; imageOnlyPages metadata identifies those pages.")
    return {"events": events, "status": "partial" if failures else "ok", "notes": notes, "failures": failures,
            "documents": list(documents.values()), "stats": {"documents": len(documents), "revisions": len(events),
            "pdfs": sum(Path(path).suffix.lower() == ".pdf" for path in documents),
            "filesystemSnapshots": sum(event["kind"] == "document_snapshot" for event in events)}}
