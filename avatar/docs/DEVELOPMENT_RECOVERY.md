# Development paused and RAM recovered

Feature work was paused at the user's request on 1 October 2026 while other
hackathon development finishes. The release goal is paused, not completed.

The reported avatar Vite PID 6720 was independently verified against its exact
avatar/node_modules/vite command. It held 10.8 GiB of physical working set and
109 GiB of private committed memory. Free physical RAM was 0.49 GiB. Stopping
that owned process recovered RAM; the final snapshot had 11.92 GiB free.
Its existing `concurrently -k` launcher also closed the paired development API.
Ports 4317 and 4318 are intentionally left stopped during this pause.

Two small restart safeguards were saved:

- `npm run dev` now launches Vite with a 512 MiB V8 heap limit.
- Vite ignores generated `.local`, `.reference`, `test-results` and
  `playwright-report` trees for development watching.

A bounded standalone restart loaded Vite, its client, main module and Game
module with HTTP 200. It used 119 MiB physical / 167 MiB private memory in that
short check, then was stopped. The exact runaway allocation source remains
unconfirmed; this check does not establish long-term stability. The heap flag
bounds the V8 heap rather than all external/native allocations.

The built native previews remain running and both `/healthz` checks returned
`ok`: voice-only at `http://127.0.0.1:43941`, and the read-only Savia validation
beta at `http://localhost:43942`. Savia's existing port 43800 listener was
preserved. No bank, voice-provider, cloud/GPU or CI job was started for recovery.
Saved source, credential files and unrelated processes were preserved.

Resume development with `npm run dev` only when feature work is resumed. Existing
production validation is recorded in [the native validation ledger](OPENROUTER_NATIVE_VALIDATION.md);
Portuguese listening and joined spoken banking acceptance remain open.
