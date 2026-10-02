# Playable development history

The static page in `web/dev-history/` brings together GitHub, Slack, Codex, FLUJO, project documentation and infrastructure evidence. It presents the development process as a sequential replay with a temporal system landscape, actual conversation trees, saved FLUJO execution graphs and machine inventory. Workstreams cover backend, MCP, dataset, frontend, deployment, review, steering, research and CI.

## Rebuild

From the repository root, run Python 3.11 or later:

```powershell
python scripts/build_dev_history.py
python scripts/serve_dev_history.py
```

Open `http://127.0.0.1:43821/`. You can also open `web/dev-history/index.html` directly after building: the page and full-text message shards work without a server or internet connection.

Each rebuild reads the current sources, merges stable event IDs, normalizes timestamps to UTC, and writes `history.json`, a smaller browser index, message body shards, screened Slack image assets and a collection report. The page displays dates in `America/Bogota`. Full source text loads when an event is opened. Search covers event titles and text previews; the complete JSON contains captured text after privacy filtering.

The default snapshot starts on **Friday, September 25, 2026 at 00:00 Bogotá time** (`2026-09-25T05:00:00Z`). Earlier timestamped records are excluded across all sources, including offline builds and retained captures. Friday itself is included. Set `history_start` to an explicit timestamp with its UTC offset to change the start date. Session/machine creation dates can remain earlier when they explain activity inside the snapshot window; they are provenance rather than replayed earlier messages.

The generated data and source caches are local artifacts, ignored by Git because they include private team conversations. The HTML, CSS, JavaScript and collectors are versionable. The preview server exposes only `web/dev-history/` on loopback.

## Source access

| Source | Collector access | Included history |
| --- | --- | --- |
| GitHub | Existing `gh` CLI login; read-only API calls | Local and remote commits across normal refs, PRs and their commits/reviews/comments, issues, timeline changes, GitHub Actions runs and job/step outcomes |
| Slack | Configured `slack-flujo` HTTP MCP server in Codex's configuration | Permitted joined public/private channels, paginated messages and thread replies; reaction snapshots and screened image attachments. DMs, group DMs, find-a-team, challenge-help and technical-help are excluded before reads. |
| Codex | Local read-only state index and active/archived rollout files | Project-folder user/assistant messages, subagent ancestry and relevant saved automation configurations |
| FLUJO | Read-only `docker exec` in `flujo-slack-flujo-1` | All workspace conversation messages and recovered append-only message log entries, including development and test runs |
| Docs | Local Git history and project files | Markdown/text, safe CI workflow YAML and PDF text, with revision timestamps and explicitly labeled filesystem snapshots |
| Infrastructure | Read-only Docker and authenticated Fly CLI; persisted project tool outputs and CI reports | Docker lifecycle and retained timestamped logs, Fly releases and Machine events, executed build/deploy commands and output, local/Modal CI results |
| Agent topology | Project Codex rollouts; persisted FLUJO conversations, tasks, versioned graphs and execution logs | Exact spawn/dispatch/steer targets, parent/child chats, observed lifetimes, saved graph versions, node transitions and authoritative completion records |

The Slack adapter calls the same connected MCP endpoint used in Codex; it has an explicit allowlist of read-only tools and never sends a Slack message. Override its endpoint with `HISTORY_SLACK_MCP_URL` if needed. Keep the MCP service running for live refreshes. GitHub needs `gh`, FLUJO needs Docker, and PDF extraction uses `pypdf` when available (including the Codex bundled Python runtime). Missing access is reported in the page and collection report.

No timestamp is invented for a message. Git commits use committer time and retain author time. Uncommitted document snapshots use labeled filesystem modification time. Missing timestamps, corrupt records, unavailable sources, deleted content, skipped attachments and read failures appear in coverage notes. Source APIs provide their latest observable message/comment bodies; prior edits and deleted Slack text cannot be reconstructed. Saved automation settings establish configuration history, not evidence that an automated run succeeded.

## Other rebuild modes

```powershell
# Re-render saved source snapshots without GitHub, MCP or Docker access.
python scripts/build_dev_history.py --offline

# Refresh selected sources and reuse the other saved snapshots.
python scripts/build_dev_history.py --only slack
python scripts/build_dev_history.py --only infrastructure topology

# Return exit code 2 if a source is partial or unavailable.
python scripts/build_dev_history.py --strict

# Optional settings, with no credentials in the configuration file.
python scripts/build_dev_history.py --config scripts/dev_history.config.example.json
```

A live source outage retains its previous snapshot and marks it as stale/partial. Successful refreshes also retain previously captured event IDs that are no longer returned, marking their prior capture time rather than assuming a deletion date. Fresh content replaces matching IDs. `--offline` uses the last saved collection time for every source. Collection output is atomically replaced, so a refresh leaves a usable prior artifact until the new file is ready.

## Privacy and Slack media

Privacy exclusions override event retention. Every rebuild, including `--offline` and a live-source failure, purges disallowed Slack conversations from saved source caches. Emails, international/grouped phone numbers, labelled contact numbers, structured contact/address/identity fields and credentials are masked across all source text and nested records. Team names remain visible. Stable timestamps, source IDs, commit hashes, ports and graph identifiers remain usable. Confidently identified copies of excluded Slack transcripts inside tool outputs are replaced by an explicit privacy marker while preserving the enclosing event's chronology. Old generated body shards and image assets absent from the new export are removed.

Additional channel names or IDs can be supplied through `slack_exclude_channels`. Configured inclusions cannot override the hard DM/help-channel policy. These filters affect generated archives and caches; they do not change the source Slack workspace, FLUJO database or Codex rollouts.

Reaction chips show counts observed when Slack was captured. Slack does not supply historical reaction timestamps through this connector, so reactions are attached to the message rather than replayed as invented later events. Image pixels are retrieved through the read-only `slack_read_file` tool, without private image URLs or bearer tokens. The collector strips image metadata and screens images locally with Windows OCR and the shared contact redactor. It exports local PNGs only when screening succeeds without detecting contacts. Images containing contacts, unsupported formats and failed/unavailable OCR appear as attachment placeholders. OCR can miss text; the collection notes record that limitation.

Image collection uses Pillow and the Windows PowerShell 5.1 / Windows OCR runtime with an installed recognition language. Other hosts still rebuild the text and reaction history; unavailable image screening fails closed. Existing screened local assets can be reused during offline rebuilding. No image or OCR text is sent to an external recognition service, and raw downloaded pixels/OCR text are not cached. `slack_images: false` disables new image downloads.

## Reading the story

“Every record · in order” is the default. It visits every record selected by the archive filters, one rendered frame or more per record. The player never jumps a batch to catch up with elapsed wall time. Dwell controls adjust reading time; speed adjusts dwell, and a manual seek is an explicit jump. The full archive is selected initially. Unchecking “All captured activity” applies inferred development relevance. Workstreams remain multi-label keyword annotations.

“Narrated chapters” presents authored prose from `scripts/history_narrative.json`, tied to cited original records in `scripts/history_story.json`. It is a chapter presentation, with evidence beside the narration. Reading durations follow prose length. It does not claim to replay every message. New live source events are collected automatically on rebuild; new editorial chapters can be added by updating these two JSON files.

Cinema mode fills the browser viewport with the graph, shared controls and source pane; Escape exits it. Graphs support pan, Ctrl-scroll zoom, fit, minimap navigation and provider pagination.

The source pane recreates recognizable Slack, FLUJO and Codex chat chrome around actual captured content, with previous messages from the same conversation. Infrastructure records appear as terminal receipts; GitHub records as repository activity. Full original bodies and provenance remain available in the event dialog and complete JSON.

The graph views share the selected record's timestamp. Traffic advances only for that record when an explicit dispatch, node transition or provider event identifies the route; reference/configuration edges remain static. Pausing freezes event progress. Dimmed structures are later evidence. Agent bars show creation through last observed activity, which establishes overlapping conversation activity rather than continuous CPU use. A last message is not a completion unless a lifecycle record establishes it.

FLUJO graphs retain saved graph versions and their recorded node ordering, with a shared spacing transform across versions so cards remain readable without overlap. Agent families use fixed chronological slots rather than being reordered on each message. Unattributed records retain the last attributed graph, and the camera moves when the relevant node/context changes rather than on every message. A declaration establishes configuration, not execution. Node highlights distinguish an execution event from the last entered node used as message context. Parent logs that forward a child execution preserve both the observing and executing sessions; real parent/child execution switches remain visible. Codex-provider bindings visible in current FLUJO state are explicitly snapshots when local historical provider rollouts are unavailable.

Machine cards show Docker/Windows, Fly region, or Modal location when the sources establish it. Builds and deployments have separate evidence receipts. Live inventory cannot backdate a current machine state. Retained logs and provider event buffers are incomplete by design, so the coverage panel records their limits; the collector also mines saved project tool output for removed containers and older deployments. Exact executed commands are exported after credential redaction, but environment variables, keys, arbitrary container configuration and hidden agent reasoning are excluded.

The graph design follows [D3's temporal network example](https://observablehq.com/@d3/temporal-force-directed-graph) and the coordinated graph/activity approach described in [LargeNetVis](https://arxiv.org/abs/2208.04358). Provider interpretation follows the [Fly Machines API](https://fly.io/docs/machines/api/machines-resource/). The delivered page uses local HTML/CSS/Canvas with no CDN or external visual library dependency.

## Verification

```powershell
python -m unittest discover -s tests -p "test*history*.py"
node --test tests/dev_history_replay.test.cjs tests/dev_history_graph.test.cjs
node --check web/dev-history/app.js
node --check web/dev-history/graph-scene.js
```

The collector tests cover exact timestamps, Slack pagination/thread/media parsing, persistent privacy purging during offline builds/live failures/retention, embedded private Slack tool outputs, contact and credential removal, fail-closed image handling, stale pixel cleanup, Codex projection/fork deduplication, safe document selection, offline full-text shards, exact agent targets, execution attribution and machine lifecycle provenance. Replay engine tests verify all records survive large time gaps and high speed. Graph tests use the actual local capture when available to check collisions and stable positions across dated graphs, conversation families and forwarded child contexts. UI checks should cover playback, seek, source filters, full-text loading, image/reaction rendering, mobile layout and keyboard controls.
