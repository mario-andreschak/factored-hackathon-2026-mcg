# Fictional local release candidate

This portal uses new generated fictional customers, current-date transactions,
the shipped Banking MCP `Service` inside the project host, explicit consent,
simulated intake receipts, and durable customer follow-ups. Language stages use
the existing general-purpose FLUJO completion interface. The bank transport is
in-process; this launch does not establish a network MCP or native-flow deployment.
The existing worker, bank policies, datasets and ledgers remain separate.

From the repository root, install the declared Python runtime dependencies and
build the portal:

```powershell
python -m pip install -r requirements-dispute.txt
npm ci --prefix frontend --no-audit --no-fund
npm run build --prefix frontend
```

Prepare a new private instance. Choose a new directory for each new fixture;
preparation refuses nonempty destinations. On Windows, restrict its ACL before
recording or sharing the browser:

```powershell
python deploy/rc/run.py --prepare --private-dir private/rc-runtime-20261004
icacls private/rc-runtime-20261004 /inheritance:r /grant:r "$($env:USERNAME):(OI)(CI)F"
python deploy/rc/run.py --private-dir private/rc-runtime-20261004
```

Open <http://127.0.0.1:43900>. Read the generated `demo_code` privately from
`private/rc-runtime-20261004/fixture.json`; choose Mexico, Colombia or Argentina.
Do not print the code, signer, session cookies or private fixture JSON into
submission artifacts. The private fixture is regenerated rather than shipped.

The launcher checks that the configured model is listed by FLUJO before starting.
The default is `model-GPT-6 Luna` at <http://localhost:43420>; use `--flujo-url`
and `--model` for another existing, authorized generic model. Language failures
remain workflow failures or handoffs, never fictional successful model replies.
Each language stage has a 90-second budget matching the transport;
the full customer task has the host's 450-second deadline. Initial measurements
of the default 15-second stage budget are retained as failed attempts.

`/healthz` reports the dataset and host state. Private `runtime.json` records the
runtime boundary. `observations.jsonl` contains only observed model-stage status,
token counts, latency and bank read/action operation timings. It contains no
customer text, prompts, signed assertions or bank identifiers. Authored fixture
ledger coverage is disclosed as synthetic; it is not observed bank operation.

Keep the same private directory across a restart to preserve receipts, customer
sessions and follow-ups. Never replace its bank database or copy it into a shared
deployment. Restart this candidate only after coordinating active measurements.
Stop its console with Ctrl+C.

The authorized fast-provider profile is a separate project adapter. It reuses
the existing private voice-provider key, checks the live provider model catalog,
and makes bounded plain language completions without tools. Select it explicitly:

```powershell
python deploy/rc/run.py --private-dir private/rc-runtime-20261004 --provider openrouter
```

Its configured default is `google/gemini-3.1-flash-lite` with 30 seconds per
stage. The receipt identifies direct OpenRouter execution; FLUJO remains the
separate generic infrastructure. The provider receives fictional bounded language
inputs, never signing keys or bank action capabilities. Do not switch profiles
during a recorded journey. The complete receipt, including stage status, remains
necessary to distinguish usable model outputs from safe fallback responses.

The voice lead runs the separate avatar on <http://127.0.0.1:43941> with
`SAVIA_UPSTREAM=http://127.0.0.1:43900` and
`SAVIA_PUBLIC_ORIGIN=http://127.0.0.1:43900`. Its read bridge uses the same
authenticated portal session. Voice provider configuration remains server-side.
Provider audio transfers and the endpointed request/response transport must be
disclosed in the demonstration; interruption is separately measured.
