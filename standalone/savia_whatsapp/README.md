# Savia WhatsApp local lab

An optional, separate feature stream on `codex/savia-whatsapp-local`, based on
hackathon **rc.3 `843da50698b559dc748bea4505d1d93483ff29b3`**. The WhatsApp MCP
is pinned to **`65d39c4d83b7e9bacdd65e46059f18f185199f8d`**, version 1.2.0.
The exported copy applies one recorded compatibility overlay: Baileys' browser
descriptor changes from `Desktop` to `Chrome`. The unmodified driver produced no
pairing QR locally; the overlay produced a real QR. This matches the upstream
[reported fix](https://github.com/WhiskeySockets/Baileys/issues/2671).
This component stays separate from the public Savia build and its customer ledger.
The owner authorized private Fly promotion on October 5, 2026; source preparation
does not establish hosted acceptance. The [deployment contract](docs/DEPLOYMENT_CONTRACT.md)
defines the private companion and paired-state handoff. Generic FLUJO remains unchanged.

The linked [ElevenLabs video](https://www.youtube.com/watch?v=1QJTfaaxVag) is a
bank-dispute voice-call demo. Its native YouTube transcript is available;
[timestamped paraphrased notes](docs/video-notes.md) describe the full sequence.
This MCP supports voice **notes**, not live WhatsApp calls. The experiment reuses
Savia's actual Moss/native audio interface, fictional profile authentication and
verified host-reply narration. It does not reproduce the video's real-bank claims,
request card numbers/OTP, freeze cards, give provisional credit or submit disputes.

## Local Windows run

Use Python 3.13, Node 22+, npm and FFmpeg. Export from this repository, then launch
inside the exported bundle. The server verifies both source manifests and rejects
an ordinary checkout, so newer main cannot silently run under the RC.3 label.
No provider key belongs in source, arguments, screenshots or the ZIP.

```powershell
$saviaLabState = Join-Path (Get-Location) 'private/whatsapp-local/state'
python -m standalone.savia_whatsapp package --destination private/whatsapp-local/bundle --mcp-repo C:\Users\Moe\Documents\GitHub\mcp-whatsapp-web
Push-Location private/whatsapp-local/bundle
python -m pip install -r standalone/savia_whatsapp/requirements.txt
Push-Location whatsapp-mcp
npm.cmd ci --no-audit --no-fund
npm.cmd run build
Pop-Location
python -m standalone.savia_whatsapp serve --state $saviaLabState --mcp-dir (Resolve-Path whatsapp-mcp).Path --provider-env C:\Users\Moe\Documents\GitHub\factored-hackathon-2026\private\providers\openrouter.env
Pop-Location
```

Open <http://127.0.0.1:43980>. Enter your own WhatsApp number with country code,
choose a fictional profile/language, save locally, refresh the QR and scan from
your phone's **Linked Devices** screen. This links a new device to the personal
account; the MCP cannot independently verify its own number, so the entered
number must belong to the phone you pair. Click **Start self-chat test** and wait
for success before sending a new **Message yourself** note:

- Text: `!savia Hola, ¿quién eres?`
- Voice note: under 30 seconds. All new voice notes in this self-chat are eligible
  while the test is active; ordinary unprefixed text is ignored.
- Fictional bank request: `!savia ¿Cuál es mi saldo?` uses the RC's authenticated
  host. Information is from the selected synthetic profile, never your real bank.

Savia replies with labeled exact text plus a PTT voice note. Provider failure is
shown locally; no bank outcome or message delivery is invented. Input recognition
uses the RC's configured recognition provider; the native model receives the WAV.
This requires the configured OpenRouter voice models to be available on your key.
The bridge does not rerun provider failures or uncertain WhatsApp sends.

The supervisor owns local ports **43980** (control), **43981** (MCP) and **43982**
(Savia). It refuses occupied MCP/RC ports. State and backend cwd are separate from
the original MCP checkout. Only one process may own the state directory; a leftover
`active.lock` after a crash requires operator review of its PID and private child
logs before removing that file. Do not clear session folders or RC ledgers to fix
an error. Stop the launcher normally to close its children; unlink the dedicated
device in WhatsApp when finished. Stop-after-active-turn may still deliver the
current reply; closing the launcher interrupts it and records uncertainty.

## Portable bundle and container

`package` exports the allowlisted immutable RC source, the standalone feature and
locked MCP source into a fresh directory and ZIP. `standalone-package.json` records
source pins and all file hashes. It excludes credentials, account histories,
browser profiles, cookies, generated fixtures and delivery state. A package can be
unpacked on another host and run with the same commands; set `OPENROUTER_API_KEY`
privately or pass a local provider file. The ZIP is made before npm dependencies
are installed, so it remains a small source package.

From an unpacked bundle, set the key in your shell and use:

```powershell
docker compose -f standalone/savia_whatsapp/compose.yml up --build
```

Both the local launcher and optional container default to browserless **Baileys**;
the container uses a persistent named volume. `--backend webjs` selects headless
Chrome/Edge, but two local starts hit an upstream pre-pairing navigation error;
that alternative remains unqualified. Drivers require
independent device pairing and their sessions are not interchangeable. Docker
publishes only `127.0.0.1:43980`; the account-control MCP remains internal. This
recipe is also the source context for the authorized private companion. Append
`--fly-private` to the image's existing entrypoint for its private IPv6 control
binding; this mode requires `SAVIA_WHATSAPP_OPERATOR_TOKEN` from a private secret.
All account-control API routes require operator authentication, including status
and QR retrieval. The static sign-in screen holds an expiring access token only
in page memory; it never uses cookies, URLs or browser storage for credentials.
Use an authenticated Fly tunnel on local port 43980. No public service is supported.
Source preparation changes no Fly resources, submission artifact or generic FLUJO.
The pinned Baileys store also retains an owner lease after an abrupt process kill;
changing container hostname or PID can require manual session-owner reconciliation.
Preserve the volume and credentials; automatic lease/credential deletion is not a
recovery strategy. Graceful stop is supported; crash/redeployment continuity has
not been qualified.
The launcher applies a private Unix creation mask (`077`) before creating the RC
fixture and starting children. This preserves the RC's existing generation-pin
permission gate. Pre-existing state with broader permissions can fail admission;
use a fresh lab state or explicitly reconcile directory permissions as the owner,
without resetting bank pin or ledger state.

Both WhatsApp backends can access the linked account. In particular Baileys enables
full-history synchronization into its private local store. The bridge queries only
the explicitly configured self-chat; its journal contains SHA-256 message ID
digests and delivery states, not message text/audio or raw JIDs. Backend logs,
session files and stores remain personal data and are never packaged. Incoming
audio is decoded with bounded FFmpeg work and temporary files are removed.

WhatsApp send/delivery is **not playback**. The RC adapter uses `complete:false`
playback cancellation, so generated speech never becomes the RC's heard assistant
history. User context and verified host chat context remain available; missing
assistant heard-history is an explicit limitation until there is a real playback
signal. Only the final narration is delivered after host delegation; the exact
host reply remains in the accompanying text. The adapter exposes no action routes,
and the standalone RC middleware blocks action/follow-up endpoints.

For an interrupted or unconfirmed send, inspect the self-chat before choosing
**skip uncertain delivery**. Skipping acknowledges the operator review and never
resends the original message. Previous self-chat history is baselined before Start
reports ready. Polling reads the latest 50 messages every three seconds; this local
test is not an archival importer or a high-volume message service.

## Verification

```powershell
python -m pytest standalone/savia_whatsapp/tests standalone/tests -q
```

Tests cover actual RC route/result-registration integration with a scripted
provider, strict audio completion and false playback receipts, restricted MCP
schemas, private-chat boundaries, same-second cursors, self-message direction,
echo suppression and uncertain delivery/restart behavior. Offline tests do not
prove phone pairing, personal-account delivery or human audio playback. The
dated [validation record](docs/validation.json) distinguishes these observations.

On October 5, the owner paired the personal phone, started the self-chat test,
sent a text message, confirmed both text and PTT audio replies, and stopped it.
The local journal and self-chat receipts independently matched one delivered input
and two outgoing messages with no uncertain send. A subsequent incoming PTT voice
note also produced confirmed text and PTT replies, bringing the outgoing count to
four. Opus decoding and a real native audio-input turn additionally passed using
Savia's generated sample. The bridge normalizes the pinned Baileys message identity
within the authorized chat so phone/LID address changes cannot turn its outgoing
voice into a new input; raw IDs remain unchanged for media retrieval. No playback
acknowledgement was invented, and personal session state is excluded from the bundle.
