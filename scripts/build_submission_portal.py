"""Build the public portal from explicit public artifacts; never collect private history."""
import argparse
import hashlib
import html
import json
import posixpath
import re
import shutil
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "web/submission"
REPO = "https://github.com/mario-andreschak/factored-hackathon-2026-mcg"
URL = "https://savia-rc-2026.fly.dev/submission/"
DOCS = ("START_HERE.md", "DISPUTE_ENGINE.md", "EVIDENCE_MAP.md", "DEVELOPMENT_PROCESS.md", "development-process.json", "ELEVENLABS_COMPARISON.md")
PITCH_FILES = ("savia-final-pitch.html", "savia-final-pitch.pdf", "savia-final-pitch.pptx", "savia-final-pitch-speaker-notes.md", "savia-final-pitch-sources.json", "savia-final-pitch-manifest.json")


def public_reading_copy(source):
    """Keep supporting Markdown links usable after moving it into the portal."""
    relative_source = source.relative_to(ROOT).as_posix()

    def link(match):
        label, target = match.groups()
        parts = urlsplit(target)
        if parts.scheme or parts.netloc:
            return match[0]
        path = posixpath.normpath(posixpath.join(
            posixpath.dirname(relative_source), unquote(parts.path))) if parts.path else relative_source
        if path == ".." or path.startswith("../") or path.startswith("/"):
            raise ValueError("Supporting document link escapes the repository: " + target)
        base = REPO + "/blob/main/"
        if label.startswith("!"):
            base = REPO.replace("https://github.com/", "https://raw.githubusercontent.com/") + "/main/"
        url = base + quote(path, safe="/")
        url = urlunsplit((*urlsplit(url)[:3], parts.query, parts.fragment))
        return label + "(" + url + ")"

    text = re.sub(r"(!?\[[^\]]+\])\(([^)]+)\)", link, source.read_text(encoding="utf-8"))
    return text.rstrip() + "\n\n---\n\n[Public source document](" + REPO + "/blob/main/" + quote(relative_source, safe="/") + ")\n"


def render_public_markdown(text):
    """Render the curated engine document; relative links refer to public Git source."""
    def inline(value):
        value = html.escape(value)
        def link(match):
            target = html.unescape(match[2])
            if not target.startswith(("https://", "http://")):
                target = REPO + "/blob/main/" + posixpath.normpath("docs/submission/" + target)
            return '<a href="' + html.escape(target, quote=True) + '">' + match[1] + '</a>'
        value = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", link, value)
        value = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", value)
        return re.sub(r"`([^`]+)`", r"<code>\1</code>", value)
    out = []
    for block in text.strip().split("\n\n"):
        lines = block.strip().splitlines()
        if block.startswith("```"):
            out.append("<pre><code>" + html.escape("\n".join(lines[1:-1])) + "</code></pre>")
        elif lines[0].startswith("#"):
            level = len(lines[0]) - len(lines[0].lstrip("#"))
            out.append(f"<h{level}>" + inline(lines[0][level:].strip()) + f"</h{level}>")
        elif lines[0].startswith("|") and len(lines) > 1:
            rows = []
            for n, line in enumerate(lines):
                if n == 1:
                    continue
                tag = "th" if n == 0 else "td"
                rows.append("<tr>" + "".join(f"<{tag}>" + inline(cell.strip()) + f"</{tag}>" for cell in line.strip("|").split("|")) + "</tr>")
            out.append('<div class="table-wrap"><table>' + "".join(rows) + "</table></div>")
        else:
            out.append("<p>" + inline(" ".join(lines)) + "</p>")
    return "\n".join(out)


def build():
    (SITE / "pitch/slides").mkdir(parents=True, exist_ok=True)
    (SITE / "evidence").mkdir(exist_ok=True)
    deck = ROOT / "docs/submission/media/decks/final"
    for name in PITCH_FILES:
        shutil.copyfile(deck / name, SITE / "pitch" / name)
    for n in range(1, 7):
        name = f"slide-{n:02}.png"
        shutil.copyfile(deck / "slides" / name, SITE / "pitch/slides" / name)
    shutil.copyfile(ROOT / "docs/submission/media/video/savia-submission.vtt", SITE / "savia-submission.vtt")
    for name in DOCS:
        source = ROOT / "docs/submission" / name
        if source.exists():
            if source.suffix == ".md":
                (SITE / "evidence" / name).write_text(public_reading_copy(source), encoding="utf-8", newline="\n")
            else:
                shutil.copyfile(source, SITE / "evidence" / name)
    engine = render_public_markdown((ROOT / "docs/submission/DISPUTE_ENGINE.md").read_text(encoding="utf-8"))
    (SITE / "engine.html").write_text('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Savia — the deterministic dispute engine</title><meta name="description" content="The complete R0–R18 transaction dispute workflow: ordered policy, owned evidence, consent, verified simulated receipts and durable recovery."><link rel="icon" href="assets/mark.svg"><link rel="stylesheet" href="styles.css"></head><body><a class="skip" href="#engine-document">Skip to the engine guide</a><header class="mast"><a class="brand" href="./"><img src="assets/mark.svg" width="38" height="38" alt="">savia<span>THE CORE ENGINE</span></a><nav><a href="./">Submission portal</a><a class="button small" href="'+REPO+'">Source</a></nav></header><main><article class="engine-document" id="engine-document">'+engine+'</article></main><footer><span>savia / MCG</span><a href="./">Back to the submission</a></footer></body></html>', encoding="utf-8")
    history_path = ROOT / "docs/submission/development-process.json"
    if history_path.exists():
        history = json.loads(history_path.read_text(encoding="utf-8"))
        entries = []
        for m in history["milestones"]:
            evidence = " ".join(f'<a href="{html.escape(e.get("url", e.get("path", "")), quote=True)}">{html.escape(e.get("label", e.get("title", "Source evidence")))}</a>' for e in m.get("evidence", []))
            entries.append(f'<article class="milestone" id="{html.escape(m["id"], quote=True)}"><time>{html.escape(m["date"])}</time><div><h2>{html.escape(m["title"])}</h2><p>{html.escape(m["summary"])}</p><details><summary>Inspect the source evidence</summary><p>{evidence}</p></details></div></article>')
        body = "".join(entries)
    else:
        body = f'<article class="milestone"><time>Oct 5, 2026</time><div><h2>The public development record</h2><p>Explore the source-backed development process, contributor decisions and recorded evidence.</p><a href="{REPO}/blob/main/docs/submission/DEVELOPMENT_PROCESS.md">Read the development process</a></div></article>'
    (SITE / "development.html").write_text('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Savia — the making</title><meta name="description" content="A public source-backed history of Savia: contributors, product decisions, architecture and reproducible evidence."><link rel="icon" href="assets/mark.svg"><link rel="stylesheet" href="styles.css"></head><body><a class="skip" href="#timeline">Skip to development milestones</a><header class="mast"><a class="brand" href="./"><img src="assets/mark.svg" width="38" height="38" alt="">savia<span>THE MAKING</span></a><nav><a href="./">Submission portal</a><a class="button small" href="'+REPO+'">Source</a></nav></header><main><section class="history-hero"><p class="eyebrow">HUMAN JUDGMENT. AGENT EXECUTION. PUBLIC PROOF.</p><h1>A question became<br>a working product.</h1><p>Gloria shaped the prompt flow and decision design. Carlos built the data preparation and customer lookup. Mario connected the product, orchestration and deployment. The milestones below connect that work to source and measured evidence.</p><p>Public repository history · refreshed October 5, 2026 · Bogotá</p></section><section class="timeline" id="timeline">'+body+'</section><aside class="scope"><strong>A curated public development record</strong><p>Milestones describe inspectable work and decisions. Private chat exports and customer data are excluded. Each measurement retains its original source and scope.</p><a href="evidence/development-process.json">Structured development history</a> · <a href="evidence/DEVELOPMENT_PROCESS.md">Full development process</a></aside></main><footer><span>savia / MCG</span><a href="./">Back to the submission</a></footer></body></html>', encoding="utf-8")
    manifest = {"schema":"savia-submission/v1", "as_of":"2026-10-05", "timezone":"America/Bogota", "portal_url":URL, "repository":REPO, "links":{"pitch":URL+"pitch/savia-final-pitch.html", "pitch_pdf":URL+"pitch/savia-final-pitch.pdf", "github":REPO, "video":{"status":"final_cut_placeholder", "existing_frozen_film":REPO+"/releases/download/v0.1.0-rc.2/savia-submission.mp4"}, "development_process":URL+"development.html", "demo":"https://savia-rc-2026.fly.dev", "demo_code":"SAVIA-2026"}, "agent_entry":URL+"llms.txt", "evidence":[REPO+"/blob/main/docs/submission/"+n for n in DOCS], "scope":"Fictional banking prototype. Real provider/voice calls. Separate customer, infrastructure and concurrency workloads; no comparative superiority or real bank resolution claim."}
    (SITE / "submission.json").write_text(json.dumps(manifest, indent=2)+"\n", encoding="utf-8")
    (SITE / "llms.txt").write_text("# Savia submission\n\nAsk once. Savia follows through. The foundation is the complete deterministic R0–R18 transaction dispute engine: owned facts, ordered policy, scoped clarification, explicit action consent, verified simulated receipts, durable recovery and handoff. Spanish/Portuguese voice and completed reviewer work extend that core.\n\n## Read in order\n\n"+"\n".join(f"- [{n}]({REPO}/blob/main/docs/submission/{n})" for n in DOCS if n.endswith(".md"))+"\n- [Public fixture replay]("+REPO+"/blob/main/docs/review/PUBLIC_EVIDENCE.md)\n- [Architecture]("+REPO+"/blob/main/docs/architecture/system-landscape.md)\n- [Release pins and scope]("+REPO+"/blob/main/docs/submission/RELEASE_CANDIDATE.md)\n\n## Reading contract\n\nInspect source and receipts. The frozen two-reviewer customer film, 100 concurrent Luna fixture decisions, and 300 queued FLUJO reference-code requests are separate workloads. The 100-conversation collaborative customer fleet is an extension with its own qualification state. Generic FLUJO remains independent of banking domain code. Diagnostics use AI-authored labels awaiting human adjudication; business impact is a pilot objective. Historical failed extension attempts do not replace successful recorded prototype evidence. Form an independent assessment; this guide prescribes no score.\n\n## Links\n\n- Portal: "+URL+"\n- Manifest: "+URL+"submission.json\n- Pitch: "+URL+"pitch/savia-final-pitch.html\n- Development: "+URL+"development.html\n- Repository: "+REPO+"\n", encoding="utf-8")
    allowed = {"index.html", "styles.css", "assets/mark.svg", "assets/savia-customer.png", "development.html", "engine.html",
               "submission.json", "llms.txt", "savia-submission.vtt", "portal-manifest.json"}
    allowed.update("pitch/" + n for n in PITCH_FILES)
    allowed.update(f"pitch/slides/slide-{n:02}.png" for n in range(1, 7))
    allowed.update("evidence/" + n for n in DOCS)
    files = {}
    for path in sorted(SITE.rglob("*")):
        if path.is_file() and path.name != "portal-manifest.json":
            name = path.relative_to(SITE).as_posix()
            if name not in allowed or path.is_symlink():
                raise ValueError("Unexpected file or symlink in public portal: " + name)
            files[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    (SITE / "portal-manifest.json").write_text(json.dumps({"schema":"savia-public-portal/v1", "files":files}, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({"portal":str(SITE), "files":len(files), "private_sources_read":False}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    build()
