# Supervised native session on host Node

This is the supported setup for one operator-prepared PersonaPlex session. It
is a bounded private candidate, with one fixed launch role and one admitted
stream. It is not a continuously available voice service. The worker's
600-second lifetime includes creation, verification and model warmup; readiness
can take up to 240 seconds. A consumed or expired worker needs a new explicit
operator launch. Browser clicks cannot provision or restart GPU resources.

Use Node 22+, Python and the already configured local Modal operator profile.
The private pinned cache must already exist at
`avatar/.local/personaplex-browser/cache.json`. Keep cache/lease files ignored,
private and outside `dist`. The cached worker source must match the current
reviewed runtime. After a worker-source change, the separately invoked
`--refresh-worker` copies source over the existing private cache; it spends CPU
build compute and performs no GPU launch or model download. First-time gated
weight preparation is a separate operator prerequisite.

## Start the application

In a terminal at the repository's `avatar` directory, choose an isolated
loopback production server. These settings leave recognition and banking off:

```powershell
$env:NODE_ENV='production'
$env:AVATAR_HOST='127.0.0.1'
$env:AVATAR_PORT='4318'
$env:AVATAR_PUBLIC_ORIGIN='http://127.0.0.1:4318'
$env:AVATAR_VOICE_PROVIDER='personaplex'
$env:AVATAR_PERSONAPLEX_LEASE_FILE=Join-Path (Get-Location).Path '.local/personaplex-browser/lease.json'
$env:AVATAR_BACKGROUND_ASR=''
$env:AVATAR_NATIVE_READ_BRIDGE=''
$env:SAVIA_UPSTREAM=''
$env:SAVIA_PUBLIC_ORIGIN=''
npm run build
if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
npm start
```

Do not replace an already owned listener on 4318. Use an available port and its
matching origin if another process owns it. Explicit `personaplex` selection
keeps any server-only Gemini/OpenAI key from selecting a different native path.
The npm start script reads ignored environment files; no credential is copied
to frontend code by these commands.

## Prepare one intentional live launch

In a second terminal at `avatar`, inspect the free local plan:

```powershell
python experiments/personaplex_browser.py --plan
```

The following separate command intentionally spends one bounded A100 worker.
Choose `moss`, `orbit` or `spark` before launch; keep this terminal running:

```powershell
python experiments/personaplex_browser.py --execute --avatar moss
```

The launcher validates the existing cache, warms the model and publishes a
private lease only after authenticated readiness. Wait for its safe `ready`
receipt before opening `http://127.0.0.1:4318` and clicking the eyes. The
application rereads the lease; restarting Node after worker readiness is not
required. One voice session uses that fixed role and NATM1 voice. Typing,
selecting an incompatible character or ending voice consumes it; the current
session cannot be resumed with the same lease.

The agreed minimum new-start budget is 120 remaining worker seconds, checked
against the trusted lease at discovery, admission, handshake and worker ready.
Five focused boundary/lifecycle regressions pass in the 25-case relay suite;
the full source and current image also pass 93 units/one optional skip. The
current browser rerun passes 64 cases/one optional real-upstream skip. This
policy never shortens an already admitted stream: capture/observer/monitor
continue below 120 seconds and stop at the original expiry with no grace. This is a private-session floor,
not a promise that a 460-second Savia read finishes before native expiry. The
lease's actual remaining time, rather than 600 seconds after connection, bounds
the voice session.

## Stop and optional capabilities

Use **End voice** in the pause menu or close the browser. Wait for the launcher's
`ended` receipt with `terminationConfirmed:true`; acknowledgment alone does not
confirm worker exit. Ctrl+C in the launcher also enters bounded cleanup. Treat
`cleanup_unconfirmed` as an operator cleanup requirement; the fixed worker
lifetime remains its final backstop. Stop the Node terminal separately. Never
leave the launcher unattended or turn this command into an automatic retry.

Optional `AVATAR_BACKGROUND_ASR=openrouter` uses the existing private OpenRouter
key for completed utterance recognition while PersonaPlex continues native
audio. Optional `AVATAR_NATIVE_READ_BRIDGE=readonly` additionally requires a
fixed Savia upstream, its exact public origin and the user's embedded login.
Those capabilities remain opt-in; read results appear in Savia/captions and
native output is held during work. No task facts reach the native model, and
bank-result narration remains disabled. Their actual joined qualification is
tracked in [release evidence](RELEASE-CHECKLIST.md).

The default Compose deployment does not forward a PersonaPlex lease path or
mount its directory, so it cannot start this native provider. Current Docker
qualification covers packaging and disabled admission only. A future explicit
operator override must mount the private lease **directory**, preserving atomic
heartbeat replacements and UID1000-readable restrictive permissions; mounting
only `lease.json` can retain an old inode. That override requires its own
qualification before PersonaPlex-in-Docker support is claimed.

See [relay contract](PERSONAPLEX_RELAY.md) for fixed credentials, clocks, expiry
and cleanup, and [read bridge](NATIVE-READ-BRIDGE.md) for task ownership.
