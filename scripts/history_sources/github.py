"""Read-only GitHub and Git history collector, using existing gh authentication.

No credentials are read by this module. Failed endpoints leave successful data
intact and are reported in the source coverage. All REST collections paginate.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import subprocess
from urllib.parse import quote, urlencode


class CollectionError(RuntimeError):
    pass


def _run(args: list[str], repo: Path, timeout: int = 180) -> str:
    try:
        result = subprocess.run(args, cwd=repo, capture_output=True, encoding="utf-8",
                                errors="replace", timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CollectionError(f"{args[0]} could not complete: {type(exc).__name__}") from exc
    if result.returncode:
        # gh stderr can echo private URLs, but never prints an auth token here.
        raise CollectionError(result.stderr.strip()[:800] or f"{args[0]} exited {result.returncode}")
    return result.stdout


def _utc(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except ValueError:
        return None


def _repository(repo: Path, config: dict) -> tuple[str | None, str]:
    configured = config.get("github_repository") or config.get("github_repo")
    hostname = config.get("github_hostname", "github.com")
    if configured:
        return str(configured).strip("/"), hostname
    try:
        remote = _run(["git", "remote", "get-url", config.get("github_remote", "origin")], repo).strip()
    except CollectionError:
        return None, hostname
    match = re.search(r"(?:https?://|ssh://git@|git@)([^/:]+)(?::|/)([^/]+/[^/]+?)(?:\.git)?/?$", remote)
    return (match.group(2), match.group(1)) if match else (None, hostname)


def _api(endpoint: str, repo: Path, hostname: str, paginate: bool = True) -> object:
    args = ["gh", "api", "--hostname", hostname, "-H", "Accept: application/vnd.github+json", endpoint]
    if paginate:
        args.extend(["--paginate", "--slurp"])
    data = json.loads(_run(args, repo))
    if paginate:
        return [item for page in data for item in page] if all(isinstance(page, list) for page in data) else data
    return data


def _event(event_id: str, timestamp: str | None, kind: str, title: str, body: str = "",
           actor: str = "", url: str = "", thread_id: str = "", tags: list | None = None,
           metadata: dict | None = None) -> dict | None:
    timestamp = _utc(timestamp)
    if not timestamp:
        return None
    return {"id": event_id, "timestamp": timestamp, "source": "github", "kind": kind,
            "title": title, "body": body or "", "actor": actor or "", "url": url or "",
            "threadId": thread_id or "", "tags": tags or [], "metadata": metadata or {}}


def _local_commits(repo: Path, config: dict, repository: str | None, hostname: str) -> tuple[list, dict]:
    include_internal = config.get("github_include_internal_refs", False)
    ref_args = ["git", "for-each-ref", "--format=%(refname)"]
    if not include_internal:
        ref_args.extend(["refs/heads", "refs/remotes", "refs/tags"])
    refs = [line for line in _run(ref_args, repo).splitlines() if line]
    if not refs:
        refs = ["HEAD"]
    fmt = "%H%x00%aI%x00%cI%x00%an%x00%ae%x00%cn%x00%ce%x00%P%x00%D%x00%B%x00"
    raw = _run(["git", "log", "--format=" + fmt, *refs, "--"], repo)
    fields = raw.split("\0")
    events = []
    for offset in range(0, len(fields) - 9, 10):
        sha, authored, committed, author, email, committer, committer_email, parents, decorations, body = fields[offset:offset + 10]
        sha = sha.strip()
        if not re.fullmatch(r"[a-f0-9]{40,64}", sha):
            continue
        prefix = f"https://{hostname}/{repository}" if repository else ""
        event = _event("git:commit:" + sha, committed or authored, "commit", body.splitlines()[0] if body.strip() else sha[:12],
                       body.rstrip(), author, "", "commit:" + sha,
                       ["commit", "local-git"] + (["merge"] if len(parents.split()) > 1 else []),
                       {"sha": sha, "authoredAt": _utc(authored), "committedAt": _utc(committed),
                        "authorEmail": email, "committer": committer, "committerEmail": committer_email,
                        "parents": parents.split(), "refsAtTip": decorations, "collectedFrom": ["local-git"],
                        "repositoryUrl": prefix})
        if event:
            events.append(event)
    return events, {"refs": refs, "includesInternalRefs": bool(include_internal), "commitCount": len(events)}


def collect(repo: Path, config: dict) -> dict:
    """Return canonical events and explicit coverage; never mutates Git or GitHub."""
    repo = Path(repo)
    repository, hostname = _repository(repo, config)
    events: dict[str, dict] = {}
    notes: list[str] = []
    failures: list[dict] = []
    counts: dict[str, int] = {}
    local = {}
    try:
        local_events, local = _local_commits(repo, config, repository, hostname)
        events.update({item["id"]: item for item in local_events})
        counts["localCommits"] = len(local_events)
    except CollectionError as exc:
        failures.append({"endpoint": "local-git", "error": str(exc)})
    if not config.get("github_enabled", True):
        return {"events": list(events.values()), "status": "ok" if events else "unavailable",
                "notes": ["Remote GitHub collection disabled by configuration."], "stats": counts,
                "repository": {"fullName": repository, "hostname": hostname}, "local": local}
    if not repository or not shutil.which("gh"):
        notes.append("Remote GitHub unavailable: configure github_repository and install/authenticate GitHub CLI (gh).")
        return {"events": list(events.values()), "status": "partial" if events else "unavailable",
                "notes": notes, "stats": counts, "repository": {"fullName": repository, "hostname": hostname}, "local": local}

    base = "repos/" + repository
    prefix = f"https://{hostname}/{repository}"

    def fetch(endpoint: str, paginate: bool = True):
        try:
            return _api(endpoint, repo, hostname, paginate)
        except (CollectionError, ValueError, TypeError) as exc:
            failures.append({"endpoint": endpoint, "error": str(exc)})
            return [] if paginate else {}

    def add(event: dict | None):
        if event:
            events[event["id"]] = event

    def add_commit(commit: dict, origin: str):
        sha = commit.get("sha")
        if not sha:
            return
        record = commit.get("commit", {})
        author = record.get("author", {}) or {}
        committer = record.get("committer", {}) or {}
        body = record.get("message", "")
        key = "git:commit:" + sha
        current = events.get(key)
        if current:
            sources = current["metadata"].setdefault("collectedFrom", [])
            if origin not in sources:
                sources.append(origin)
            current["metadata"]["githubAuthor"] = (commit.get("author") or {}).get("login")
            current["url"] = commit.get("html_url") or current["url"]
            return
        add(_event(key, committer.get("date") or author.get("date"), "commit", body.splitlines()[0] if body else sha[:12],
                   body, (commit.get("author") or {}).get("login") or author.get("name", ""),
                   commit.get("html_url", f"{prefix}/commit/{sha}"), "commit:" + sha,
                   ["commit"] + (["merge"] if len(commit.get("parents", [])) > 1 else []),
                   {"sha": sha, "authoredAt": _utc(author.get("date")), "committedAt": _utc(committer.get("date")),
                    "authorEmail": author.get("email"), "committer": committer.get("name"),
                    "parents": [item.get("sha") for item in commit.get("parents", [])], "collectedFrom": [origin],
                    "verification": record.get("verification", {})}))

    endpoints = {
        "repository": (base, False),
        "branches": (base + "/branches?per_page=100", True),
        "tags": (base + "/tags?per_page=100", True),
        "pullRequests": (base + "/pulls?state=all&per_page=100", True),
        "issues": (base + "/issues?state=all&per_page=100", True),
        "issueComments": (base + "/issues/comments?per_page=100", True),
        "reviewComments": (base + "/pulls/comments?per_page=100", True),
        "commitComments": (base + "/comments?per_page=100", True),
        "workflowRuns": (base + "/actions/runs?per_page=100", True),
    }
    results = {}
    workers = max(1, min(int(config.get("github_workers", 4)), 8))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fetch, endpoint, paginate): key for key, (endpoint, paginate) in endpoints.items()}
        for future in as_completed(futures):
            key = futures[future]
            results[key] = future.result()
            if isinstance(results[key], list):
                counts[key] = len(results[key])

    run_pages = results.get("workflowRuns", [])
    runs = [run for page in run_pages if isinstance(page, dict) for run in page.get("workflow_runs", [])]
    counts["workflowRuns"] = len(runs)

    repo_info = results.get("repository") or {}
    if repo_info.get("created_at"):
        add(_event("github:repository:" + repository, repo_info["created_at"], "repository_created",
                   "GitHub repository created", repo_info.get("description") or "", (repo_info.get("owner") or {}).get("login", ""),
                   repo_info.get("html_url", prefix), "repository:" + repository, ["milestone"],
                   {"private": repo_info.get("private"), "defaultBranch": repo_info.get("default_branch")}))

    # Traverse the default branch first. A branch whose tip is already in a
    # successfully traversed ancestry needs no second ancestry request.
    ancestry_complete: set[str] = set()
    branches = results.get("branches", [])
    branches.sort(key=lambda item: (item.get("name") != repo_info.get("default_branch"), item.get("name", "")))
    refs = [(item.get("name", ""), (item.get("commit") or {}).get("sha")) for item in branches]
    refs.extend(("tag:" + item.get("name", ""), (item.get("commit") or {}).get("sha")) for item in results.get("tags", []))
    for ref_name, sha in refs:
        if not sha or sha in ancestry_complete:
            continue
        before = len(failures)
        commits = fetch(base + "/commits?" + urlencode({"sha": sha, "per_page": 100}))
        for commit in commits:
            add_commit(commit, "github:ref:" + ref_name)
        if len(failures) == before:
            ancestry_complete.update(item["sha"] for item in commits if item.get("sha"))
    counts["remoteReachableCommits"] = len(ancestry_complete)

    prs = results.get("pullRequests", [])
    issue_numbers = {item["number"] for item in results.get("issues", []) if "number" in item}
    pr_by_number = {item["number"]: item for item in prs if "number" in item}
    issue_numbers.update(pr_by_number)
    per_item = []
    for number in pr_by_number:
        for name, path, paginated in [
            ("detail", f"/pulls/{number}", False), ("reviews", f"/pulls/{number}/reviews?per_page=100", True),
            ("commits", f"/pulls/{number}/commits?per_page=100", True), ("files", f"/pulls/{number}/files?per_page=100", True),
        ]:
            per_item.append((number, name, base + path, paginated))
    for number in issue_numbers:
        per_item.append((number, "timeline", base + f"/issues/{number}/timeline?per_page=100", True))
    for run in runs:
        per_item.append((run["id"], "jobs", base + f"/actions/runs/{run['id']}/jobs?filter=all&per_page=100", True))
    item_results: dict[int, dict] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fetch, endpoint, paginated): (number, name) for number, name, endpoint, paginated in per_item}
        for future in as_completed(futures):
            number, name = futures[future]
            item_results.setdefault(number, {})[name] = future.result()

    for number, pr in pr_by_number.items():
        extra = item_results.get(number, {})
        pr = extra.get("detail") or pr
        thread = "github:pr:" + str(number)
        actor = (pr.get("user") or {}).get("login", "")
        tags = ["pull-request"] + [label.get("name", "") for label in pr.get("labels", [])]
        metadata = {key: pr.get(key) for key in ["number", "state", "draft", "head", "base", "merge_commit_sha",
                    "merged", "mergeable", "mergeable_state", "author_association", "requested_reviewers", "requested_teams",
                    "assignees", "labels", "milestone", "additions", "deletions", "changed_files", "commits", "comments", "review_comments",
                    "created_at", "updated_at", "closed_at", "merged_at"]}
        metadata["files"] = extra.get("files", [])
        metadata["reviews"] = extra.get("reviews", [])
        metadata["bodyVersion"] = "latest_observable"
        if pr.get("changed_files", 0) > len(metadata["files"]):
            failures.append({"endpoint": f"pulls/{number}/files", "error": "API file limit or incomplete file enumeration."})
        add(_event(thread + ":opened", pr.get("created_at"), "pr_opened", f"PR #{number}: {pr.get('title', '')}",
                   pr.get("body", ""), actor, pr.get("html_url", ""), thread, tags, metadata))
        if pr.get("merged_at"):
            add(_event(thread + ":merged", pr["merged_at"], "pr_merged", f"Merged PR #{number}: {pr.get('title', '')}",
                       pr.get("body", ""), (pr.get("merged_by") or {}).get("login", actor), pr.get("html_url", ""), thread,
                       tags + ["milestone"], {"number": number, "mergeCommit": pr.get("merge_commit_sha")}))
        elif pr.get("closed_at"):
            add(_event(thread + ":closed", pr["closed_at"], "pr_closed", f"Closed PR #{number}: {pr.get('title', '')}",
                       pr.get("body", ""), actor, pr.get("html_url", ""), thread, tags, {"number": number}))
        for commit in extra.get("commits", []):
            add_commit(commit, "github:pr:" + str(number))
        if pr.get("commits", 0) > len(extra.get("commits", [])):
            failures.append({"endpoint": f"pulls/{number}/commits", "error": "PR commit list incomplete (REST maximum is 250); branch/local Git may provide remaining commits."})
        for review in extra.get("reviews", []):
            state = review.get("state", "COMMENTED")
            add(_event("github:review:" + str(review["id"]), review.get("submitted_at"), "pr_review",
                       f"PR #{number} review: {state.replace('_', ' ').lower()}", review.get("body", ""),
                       (review.get("user") or {}).get("login", ""), review.get("html_url", ""), thread,
                       ["review", state.lower()], {"number": number, "state": state, "commitId": review.get("commit_id"),
                                                 "authorAssociation": review.get("author_association")}))

    for issue in results.get("issues", []):
        if issue.get("pull_request"):
            continue
        number = issue["number"]
        thread = "github:issue:" + str(number)
        actor = (issue.get("user") or {}).get("login", "")
        metadata = {key: issue.get(key) for key in ["number", "state", "state_reason", "labels", "assignees", "milestone", "author_association", "updated_at"]}
        metadata["bodyVersion"] = "latest_observable"
        add(_event(thread + ":opened", issue.get("created_at"), "issue_opened", f"Issue #{number}: {issue.get('title', '')}",
                   issue.get("body", ""), actor, issue.get("html_url", ""), thread, ["issue"], metadata))
        if issue.get("closed_at"):
            add(_event(thread + ":closed", issue["closed_at"], "issue_closed", f"Closed issue #{number}: {issue.get('title', '')}",
                       "", actor, issue.get("html_url", ""), thread, ["issue"], metadata))

    for name, kind in [("issueComments", "comment"), ("reviewComments", "review_comment"), ("commitComments", "commit_comment")]:
        for comment in results.get(name, []):
            number_match = re.search(r"/(?:issues|pulls)/(\d+)(?:/|$)", comment.get("issue_url") or comment.get("pull_request_url", ""))
            number = int(number_match.group(1)) if number_match else None
            thread = ("github:pr:" if number in pr_by_number else "github:issue:") + str(number) if number else "commit:" + str(comment.get("commit_id", ""))
            title = f"{'PR' if number in pr_by_number else 'Issue'} #{number} comment" if number else "Commit comment"
            metadata = {key: comment.get(key) for key in ["path", "line", "original_line", "start_line", "side", "diff_hunk", "commit_id",
                        "original_commit_id", "pull_request_review_id", "in_reply_to_id", "author_association", "updated_at", "reactions"]}
            metadata["number"] = number
            add(_event("github:" + kind + ":" + str(comment["id"]), comment.get("created_at"), kind, title,
                       comment.get("body", ""), (comment.get("user") or {}).get("login", ""), comment.get("html_url", ""),
                       thread, ["comment", "review"] if name == "reviewComments" else ["comment"], metadata))

    for run in runs:
        run_id = run["id"]
        job_pages = item_results.get(run_id, {}).get("jobs", [])
        jobs = [job for page in job_pages if isinstance(page, dict) for job in page.get("jobs", [])]
        metadata = {key: run.get(key) for key in ["id", "name", "display_title", "workflow_id", "run_number", "run_attempt",
                    "event", "status", "conclusion", "head_branch", "head_sha", "path", "created_at", "updated_at", "run_started_at"]}
        metadata["jobs"] = jobs
        metadata["headCommit"] = run.get("head_commit")
        actor = (run.get("triggering_actor") or run.get("actor") or {}).get("login", "")
        thread = "github:workflow-run:" + str(run_id)
        title = f"CI: {run.get('name') or run.get('display_title') or 'workflow'} · {run.get('conclusion') or run.get('status') or 'queued'}"
        body = "\n".join(f"{job.get('name')}: {job.get('conclusion') or job.get('status')}" for job in jobs)
        add(_event(thread + ":started", run.get("run_started_at") or run.get("created_at"), "ci_run", title,
                   body, actor, run.get("html_url", ""), thread, ["ci", "automation", run.get("conclusion") or run.get("status", "")], metadata))
        completed_at = max([job.get("completed_at") for job in jobs if job.get("completed_at")], default=None)
        if run.get("status") == "completed" and completed_at:
            add(_event(thread + ":completed", completed_at, "ci_completed", title, body, actor,
                       run.get("html_url", ""), thread, ["ci", "automation", run.get("conclusion", "")], metadata))

    timeline_count = 0
    for number, extra in item_results.items():
        thread = ("github:pr:" if number in pr_by_number else "github:issue:") + str(number)
        for item in extra.get("timeline", []):
            kind = item.get("event", "")
            # These are already represented by richer endpoint records.
            if kind in {"commented", "reviewed", "committed", "merged", "closed"}:
                continue
            timestamp = item.get("created_at") or item.get("submitted_at")
            if not timestamp:
                continue
            identifier = item.get("id") or item.get("node_id") or f"{number}:{kind}:{timestamp}"
            add(_event("github:timeline:" + str(identifier), timestamp, "github_" + kind,
                       f"{'PR' if number in pr_by_number else 'Issue'} #{number}: {kind.replace('_', ' ')}",
                       item.get("body", "") or json.dumps({key: item[key] for key in ["label", "milestone", "rename", "source"] if key in item}, ensure_ascii=False),
                       (item.get("actor") or item.get("user") or {}).get("login", ""), item.get("html_url", f"{prefix}/issues/{number}"),
                       thread, ["pull-request" if number in pr_by_number else "issue", "activity"], item))
            timeline_count += 1
    counts["timelineEvents"] = timeline_count
    counts["commits"] = sum(event["kind"] == "commit" for event in events.values())
    counts["issueApiRecords"] = counts.get("issues", 0)
    counts["issues"] = sum(not item.get("pull_request") for item in results.get("issues", []))
    counts["reviews"] = sum(event["kind"] == "pr_review" for event in events.values())
    counts["ciCompleted"] = sum(event["kind"] == "ci_completed" for event in events.values())
    counts["events"] = len(events)
    notes.append("Commit timestamps use committer time; original author times are retained in metadata.")
    notes.append("Bodies preserve the latest observable content; GitHub does not expose a complete edit/deletion history.")
    notes.append("GitHub Actions run, job and step outcomes are retained; raw console-log archives and artifact contents are not downloaded.")
    if failures:
        notes.append(f"{len(failures)} GitHub/Git endpoint(s) could not be collected completely; inspect failures.")
    return {"events": list(events.values()), "status": "partial" if failures else "ok", "notes": notes,
            "stats": counts, "failures": failures, "local": local,
            "repository": {"fullName": repository, "hostname": hostname, "url": prefix,
                           "private": repo_info.get("private"), "defaultBranch": repo_info.get("default_branch"),
                           "branches": results.get("branches", []), "tags": results.get("tags", [])}}
