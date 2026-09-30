# Savia Lite

A second, independent take on the Savia customer banking portal: **one static
page, zero dependencies, zero build step, zero network calls.**

`frontend/` is the production Savia portal — React + Vite + a FastAPI API that
reads the published organizer Parquet snapshot, needs a private config file, a
demo access code, a state volume and Docker. Savia Lite is the opposite trade:
it gives up real data and real auth in exchange for **starting anywhere in about
two seconds**, so the interaction design, the wording rules and the accessibility
work can be reviewed on any machine without provisioning anything.

```
python serve.py     ->  http://127.0.0.1:43900/
```

## Run it

Any one of these works. Nothing is installed.

```bash
# 1. the bundled server (recommended - sets correct JS MIME types)
python3 serve.py                 # -> http://127.0.0.1:43900/
./run.sh                         # same thing
./run.sh --port 8123             # pick your own port

# 2. plain stdlib, no script
python3 -m http.server 43900     # then open http://127.0.0.1:43900/

# 3. Node, if you prefer
npx --yes serve . -l 43900
```

```powershell
# Windows
.\run.ps1
.\run.ps1 --port 8123
```

Opening `index.html` straight from disk also works in Firefox. Chrome and Edge
block ES modules on `file://`, so use one of the servers above for those.

If the requested port is busy, `serve.py` moves to the next free one and prints
the URL it actually bound. Pass `--no-port-search` to fail loudly instead.

## What it does

| Area | Behaviour |
| --- | --- |
| Sign-in | Three demo profiles, no password, no session, nothing stored server-side. Picking the Brazilian profile switches the interface to Portuguese. |
| Languages | Full Spanish, Portuguese and English. All three carry an identical key set, enforced by the self check. |
| Overview | Balances grouped by currency, three products with credit utilisation, a 30-day inflow/outflow chart, and a "worth a look" list. |
| Transactions | Month-grouped list, free-text search, ten filters, four sort orders, CSV export with both date bases. |
| Detail panel | Amount, both dates, status, direction, channel, product, merchant, place, plus a charge-journey timeline. |
| Triage | Four concrete questions, an urgent lost/stolen-card shortcut, then a local review summary you can copy or download as JSON. |
| Keyboard | `/` jumps to search, `↑`/`↓` walk the list, `Esc` closes the panel or dialog, skip link, visible focus rings, ARIA labels and live regions. |
| Theming | Light and dark, `prefers-reduced-motion` respected, print stylesheet, responsive to a phone width. |

## The data is invented, on purpose

`assets/data.js` generates the entire scenario in the browser from a fixed seed.
No file in this folder reads the organizer snapshot, S3, or any customer record,
and the self check asserts that no source file can even reach the network.

The generator deliberately reproduces the *shapes* that make the real snapshot
awkward, because a demo that hides them teaches the wrong lesson:

- **Most rows carry no merchant.** About 75% of generated rows have
  `merchant_name = null`, close to the 76.7% measured in the published build.
  The interface prints "merchant not reported" and never guesses a name.
- **Two date bases.** Some events land on the calendar day *after* their
  processing day. The list uses the event date, the detail panel shows both, the
  CSV exports both, and a note explains the gap instead of hiding it.
- **Direction is not always knowable.** Only purchases, withdrawals and deposits
  get a signed amount. Transfers, payments and adjustments render unsigned with
  an explicit "direction not determined" chip.
- **Balances are snapshot values.** They are never recomputed by summing the
  listed rows, and the interface says so. Missing data is not a zero balance.

Six scenarios are hand-placed in every profile so a reviewer can exercise each
rule: an opaque acquirer descriptor, a duplicate-looking pair, a charge with no
merchant at all, a charge with its reversal entry, and a pending authorisation on
the last processing day.

## Wording rules the code enforces

These are the claims the interface is careful *not* to make. `tools/selfcheck.mjs`
asserts each one in all three languages, so the guarantee is tested rather than
promised in prose:

- a pending charge is never described as settled;
- a reversal is never described as a refund that arrived;
- an absent merchant stays unknown;
- a duplicate-looking pair is a question, never confirmed fraud;
- no screen claims a dispute, a refund, a chargeback, an agent transfer, a
  response deadline or any other bank action;
- no risk score, fraud label, customer identifier or document number is rendered
  anywhere — the generator does not even produce those fields;
- nothing here tests customer authentication, because there are no customers.

## The review summary

Finishing the triage produces a `REV-LOCAL-XXXXXXXX` object that stays in the
browser. It can be copied or downloaded; it is sent nowhere.

```json
{
  "schema": "savia-lite-local-review/v1",
  "local_only": true,
  "id": "REV-LOCAL-7KMQ2PDX",
  "reason": "unrecognised_charge",
  "transaction": { "reference": "TXS-...", "settled": false, "merchant_known": false },
  "customer_answers": { "shared": "no", "merchant": "unsure" },
  "unresolved_questions": ["..."],
  "bank_action_taken": false,
  "dispute_submitted": false,
  "refund_issued": false,
  "agent_contacted": false,
  "next_step": "Local human review; no bank decision or response deadline promised."
}
```

Facts read from the generated dataset live under `transaction`. Anything the
person clicked or typed lives under `customer_answers` and `customer_note`, and
is never promoted into the transaction facts. Ticking "my card is lost or stolen"
skips the remaining questions, sets `reason` to `security_concern` and generates
the summary immediately — an urgent security matter should not wait behind a
questionnaire.

## Check it yourself

```bash
node tools/selfcheck.mjs
```

116 assertions over the generator, the three translation tables, the formatting
helpers, the wording rules and the shipped files. Plain Node, no test framework,
no install.

## Files

```
savia-lite/
├── index.html            entry point, no external origin
├── favicon.svg           inline mark, no font or icon CDN
├── serve.py              stdlib static server, strict MIME + CSP, no-store
├── run.sh / run.ps1      one-line launchers
├── assets/
│   ├── app.js            the portal: state, views, panel, triage, keyboard
│   ├── data.js           seeded scenario generator
│   ├── i18n.js           es / pt / en, identical key sets
│   ├── format.js         timezone-safe dates, currency, CSV
│   └── styles.css        design system, light + dark, responsive, print
└── tools/selfcheck.mjs   116 assertions, no framework
```

Total shipped payload is a handful of text files; there is no `node_modules`,
no lockfile and no image to build.

## Relationship to `frontend/`

Savia Lite does not replace, import from, or modify `frontend/`. It shares the
brand and the wording discipline, and it reuses the organizer field names
(`transaction_date`, `process_date`, `merchant_name`, `transaction_status`, …) so
the screens exercise the same shapes the real API returns. It is a design and
copy reference, and a way to review the customer experience without a dataset,
a private config file or Docker.

It is not a deployment target: no real snapshot, no authentication, no
persistence, no MCP tools, no FLUJO flow. For anything involving real data or a
real handoff, use `frontend/` and the banking MCP.
