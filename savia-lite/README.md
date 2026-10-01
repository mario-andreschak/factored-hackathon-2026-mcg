# Savia Lite

A second, independent take on the Savia customer banking portal: **one static
page, zero dependencies, zero build step, zero network calls.**

```
python serve.py     ->  http://127.0.0.1:43900/
```

`frontend/` is the production Savia portal — React + Vite + a FastAPI API over
the published organizer Parquet snapshot, needing a private config file, a demo
access code, a state volume and Docker. Savia Lite makes the opposite trade: it
gives up real data and real auth in exchange for **starting anywhere in about
two seconds**, so the interaction design, the wording rules and the
accessibility work can be reviewed on any machine without provisioning
anything.

Nothing here replaces, modifies or competes with `frontend/`. It is a parallel
exploration of the same problem.

## Run it

Any one of these works. Nothing is installed.

```bash
python3 serve.py                 # -> http://127.0.0.1:43900/   (recommended)
./run.sh                         # same thing
./run.sh --port 8123             # pick your own port
python3 -m http.server 43900     # plain stdlib, no script
npx --yes serve . -l 43900       # if you prefer Node
```

```powershell
.\run.ps1                        # Windows, PowerShell 5.1 or 7+
.\run.ps1 --port 8123
```

`serve.py` is recommended only because it sets correct JavaScript MIME types,
`Cache-Control: no-store` and a restrictive CSP. If the port is busy it moves to
the next free one and prints the URL it actually bound; `--no-port-search`
fails loudly instead.

Opening `index.html` straight from disk works in Firefox. Chrome and Edge block
ES modules on `file://`, so use a server there.

## What it does

| Area | Behaviour |
| --- | --- |
| Sign-in | Three demo profiles, no password, no session, nothing stored server-side. Picking the Brazilian profile switches the interface to Portuguese. |
| Languages | Full Spanish, Portuguese and English, 277 keys each, written by hand. The self check enforces that the three key sets are identical. |
| Home | Balances per currency, product cards with credit utilisation, a 12-month SVG in/out chart, the guided tour, and "worth a look". |
| Movements | 12 months of rows grouped by month, text search, five quick-filter chips, eleven filters, four sort orders, incremental paging, CSV export carrying **both** date bases. |
| Insights | Category donut, recurring charges, and a completeness panel that states what fraction of the scenario is missing. All sums of the rows on screen — no model, no forecast, no score. |
| Detail | Full field list, a charge-journey timeline, the duplicate counterpart, and the reversal counterpart, each cross-linked. |
| Triage | Four questions, then a local `REV-LOCAL-XXXXXXXX` review summary you can copy or download as JSON. |
| Urgent path | Ticking "my card is lost or stolen" skips the questionnaire, sets `reason: security_concern` and builds the summary immediately. |
| Keyboard | `Ctrl/⌘+K` palette, `/` search, `↑ ↓` through rows, `Enter` to open, `Esc` to close, `Shift+T` theme. |
| Accessibility | Visible focus, skip link, dialogs that trap focus and return it to the opener, `prefers-reduced-motion`, light/dark, print stylesheet, breakpoints at 860px and 520px. |

## The data is invented, on purpose

`assets/data.js` generates the entire scenario in the browser from a fixed seed.
Nothing reads the organizer snapshot, S3 or any customer record, and the self
check asserts that no source file can even reach the network.

It deliberately reproduces the shapes that make the real snapshot awkward,
because a demo that hides them teaches the wrong lesson:

| Real snapshot property | Reproduced as |
| --- | --- |
| 76.7% of transactions carry no merchant | ~70–75% of generated rows have `merchant_name = null`. The UI says "merchant not reported" and never guesses. |
| 1,106,307 of 4,425,008 events land a day after `process_date` | ~23% of rows do the same. The list uses the event date, the detail shows both, the CSV exports both, and a note explains the gap. |
| Transfers, payments and adjustments carry no debit/credit indicator | Those types get `direction: unknown` and no sign. Only purchases, withdrawals and deposits are signed. |
| Balances are snapshot values | Balances are never recomputed from the rows on screen, and missing data is never read as a zero balance. |

Six hard cases are hand-placed in every profile, each reachable in one click
from the guided tour on the home page:

1. an opaque acquirer descriptor (`DLC*PAGOS DIGITALES 8829`);
2. two charges that look like one (same merchant, amount, currency, same day);
3. a pending charge with no merchant whose event lands the next day;
4. a reversal entry, which is *not* proof that a refund arrived;
5. a declined attempt, which is *not* a charge;
6. a charge in a currency other than the product's, with no conversion.

## The wording rules

Every notice exists to avoid claiming more than the data supports:

- a pending charge is never described as settled;
- a reversal entry is never described as a refund that arrived;
- a declined attempt is never described as a charge;
- an absent merchant stays unknown instead of being guessed;
- a duplicate-looking pair is a question, never a fraud finding;
- no screen claims a dispute, a refund, an agent transfer or a deadline;
- no fraud score or fraud label appears anywhere in the product.

## Verify it instead of trusting it

```bash
node tools/selfcheck.mjs      # 241 assertions, plain Node, nothing installed
```

The harness asserts the claims above rather than restating them, including:

- the generated scenario really does hit the missing-merchant, next-day-event
  and unknown-direction shares, and never produces an implausible pairing such
  as a purchase "at an ATM";
- all six hard cases are reachable for all three profiles;
- the three translations carry identical key sets, and each promise-bearing
  string still contains its negation in that language;
- no string *asserts* a dispute was filed or a refund arrived. Phrases are
  checked for negation in their own clause rather than banned outright,
  because the strings that protect the reader are exactly the ones that
  mention a refund in order to deny it;
- the local summary hard-codes `bank_action_taken: false`,
  `dispute_submitted: false`, `refund_issued: false`, `agent_transfer: false`;
- what the person typed never leaks into the transaction facts;
- an urgent card report becomes `security_concern` and asks no further
  questions;
- no source file calls the network or embeds a remote URL;
- every browser module parses, so a syntax error can never ship as a blank page.

`assets/boot.js` is loaded before the app and renders any start-up error on
screen, because a blank page is the worst outcome for somebody testing a demo.

## Files

```
index.html          page shell, loads the boot guard then the app
favicon.svg         inline mark, no remote asset
serve.py            stdlib static server: MIME types, no-store, CSP
run.sh / run.ps1    launchers
assets/data.js      seeded scenario generator and derived views
assets/i18n.js      es / pt / en, 277 keys each
assets/format.js    timezone-safe dates, money, CSV
assets/charts.js    hand-built SVG bars, donut and meters
assets/ui.js        hyperscript plus focus trap and restore
assets/app.js       the portal
assets/styles.css   design tokens, light/dark, print, breakpoints
assets/boot.js      start-up error reporter
tools/selfcheck.mjs the 241 assertions
```

## What it is not

Not a deployment target. No real data, no authentication, no persistence, no
MCP connection, no bank action. It does not test customer isolation and it does
not submit anything anywhere. Profile names are invented aliases and do not
represent any person.
