# Savia Pro

A customer banking portal served from the **published organizer snapshot** —
4,425,008 ownership-valid transactions — with a FastAPI + DuckDB service behind
a React client.

```bash
./run.sh          #  ->  http://127.0.0.1:43950/
```

This is a second, independent take on the portal in `frontend/`. It does not
replace, modify or depend on it. The two differ in substance, not in skin:

| | `frontend/` | `savia-pro/` |
| --- | --- | --- |
| Data | silver + customer-sharded gold Parquet, read per request | a **serving build** compiled once from the same lake |
| Customer identity | customer id travels with the request | the browser only ever holds a **profile slug**; the id is resolved server-side |
| Redaction | columns selected per query | one **explicit field map**; adding a column cannot publish it |
| Latency budget | lake scan | ~1 ms, queries run over a 3 MB local database |
| Verification | tests over the app | `tools/acceptance.py`, **64 live assertions** over the running API |

## Run it

```bash
./run.sh                 # installs deps, builds the serving db, builds the client, serves
./run.sh --rebuild       # re-compile the serving database from the lake
./run.sh --api-only      # skip the web build (no Node on this machine)
```

```powershell
.\run.ps1                # Windows
.\run.ps1 --api-only     # skip the web build
```

Requirements: Python 3.11+, the organizer lake mounted read-only (default
`/banking-data`, override with `SAVIA_LAKE`), and Node 20+ if you want the
bundled client. The API alone is useful without Node — it ships an OpenAPI page
at `/api/docs`.

`SAVIA_SERVING` overrides the serving file consistently in the builder, launcher
and API. A rebuild compiles to an owned temporary file, closes and reopens it
for validation, and only then atomically replaces the serving file. If the
source or verification fails, the previous serving file stays intact. Stop the
API before replacing a serving file that it already has open.

During UI work, run the service and the Vite dev server side by side:

```bash
python3 -m server.main &      # :43950
cd web && npm run dev         # :43951, proxies /api to the service
```

## Where the data comes from

`tools/build_serving.py` is the only component that touches the lake. It reads
the published build (`/banking-data/CURRENT`, currently
`20260928T235012Z-ad5cf4`, fingerprint `492b923192bf6ea2`), keeps the rows that
belong to the approved demo customers, and writes `var/serving.duckdb`.

It does three things that matter:

1. **Ownership is enforced once, at build time.** Every transaction is joined to
   a product the customer actually holds. The build fails loudly if a single row
   does not survive the join.
2. **The fraud columns never enter the serving database.** `is_fraud`,
   `fraud_score`, `_row_hash`, `_source_file`, `_run_id`, `_partition_date` and
   the owner-mismatch markers are dropped during the build, so no later bug can
   leak them.
3. **The whole snapshot is measured, not sampled.** The numbers the portal
   quotes about the dataset are computed over all 4.4 M rows during the build and
   stored alongside the data.

### Choosing the profiles

The five demo profiles are a frozen, measured selection from the published
snapshot, defined explicitly in `tools/build_serving.py`. They cover multiple
products, currencies and transaction statuses. The builder does not rerank or
silently select new customers when `CURRENT` changes: it requires every listed
customer and every selected ownership-valid transaction to survive the owned
product join. Each profile keeps its whole selected history — roughly three
years and 120–150 transactions in the named snapshot.

| slug | real shape |
| --- | --- |
| `ar-premium` | Premium, Buenos Aires. Mortgage, USD investment, one **closed** savings account. |
| `ar-basic` | The longest history in the set. 110 of 148 rows carry no merchant. |
| `co-plus` | Plus, Medellín. Ten products across COP and USD. |
| `co-blocked` | Holds a **blocked** credit card that still carries history. |
| `co-inactive` | The customer record itself is marked **inactive** at source. |

## What the snapshot actually looks like

Measured over all 4,425,008 rows, published in the app's *Data* tab:

| property | value |
| --- | --- |
| transactions with no merchant | 3,395,774 · **76.74 %** |
| transactions with no category | 2,693,520 · **60.87 %** |
| event stamped a day after processing | 1,106,307 · **25.00 %** |
| pending | 88,343 · 2.00 % |
| reversed | 44,750 · 1.01 % |
| declined | 221,234 · 5.00 % |
| distinct merchant names in the entire snapshot | **24** |
| same merchant + amount + currency within 72 h | **0** |

That last row is the one worth dwelling on. A duplicate-charge detector is the
obvious feature for an unrecognized-charge product, so this build ran one over
the whole snapshot. It found nothing — not for the demo customers, not for
anyone. The portal therefore ships the detector, runs it, and **says it found
nothing**, in a section built for exactly that outcome. Inventing a duplicate
would have demoed better and taught the reviewer something false.

The same applies to repeat merchants. Three or more charges from one merchant do
occur, but the amount swings by up to 3× between visits, so the product reports
the spread and refuses the word *subscription*.

## What it does

| Screen | What it is |
| --- | --- |
| **Sign in** | Five real customers, each described by its real shape. No password; the profile slug is exchanged for a signed session token. |
| **Home** | Balances per currency, credit utilisation, an animated 36-month flow chart, the per-rule signal list, and every product including blocked and closed ones. |
| **Movements** | Server-side search, 8 quick flags, 11 filters, 4 sort orders, month grouping, incremental paging, CSV export carrying both date bases. |
| **Insights** | Category donut with the unclassified remainder as its own slice, channel mix, top merchants, repeat merchants with their amount spread, and a completeness panel. |
| **Data** | Provenance: build id, fingerprint, lake path, every rule run over the whole snapshot with its result, and an explicit list of what this is not. |
| **Transaction drawer** | Full detail, a charge-journey timeline, and a five-step review flow producing a record with a SHA-256 over the verified facts. |

Spanish, Portuguese and English, with the source data's own vocabularies
(`Cuenta Ahorro`, `Approved`, `POS`…) translated so a Portuguese reader is never
shown a raw column value.

## The review record

Opening a review writes an append-only line to `var/state/reviews.jsonl`:

```json
{
  "id": "REV-F4901BC88E",
  "schema": "savia-pro/local-review/v1",
  "reason": "security_concern",
  "priority": "security",
  "customer_answers": {},
  "customer_note": "",
  "verified_facts": { "reference": "TRX-…", "amount": 88464.12, "...": "…" },
  "evidence": { "source": "serving_snapshot", "build_id": "20260928T235012Z-ad5cf4",
                "facts_sha256": "739994…" },
  "questions_skipped": true,
  "bank_action_taken": false, "dispute_submitted": false,
  "chargeback_requested": false, "refund_issued": false,
  "agent_transfer": false, "response_deadline_promised": false,
  "local_only": true,
  "next_step": "Local review record only. No bank decision and no response time are promised."
}
```

What the customer typed lives under `customer_answers` and `customer_note`.
What the server read lives under `verified_facts`, with a digest over it, so a
reviewer can tell whether the row changed afterwards. The two are never mixed.

Ticking *my card is lost or stolen* skips the questionnaire entirely and files
the record as a security concern, whatever reason was selected — security
outranks the form.

## Verification

```bash
python3 -m server.main &
python3 tools/acceptance.py        # 64 assertions against the live API
```

It asserts, among other things:

* every read endpoint refuses an anonymous caller;
* the catalogue contains no customer identifier, and no response anywhere
  carries one, nor a fraud flag, source key, row hash or bucket;
* asking for **another customer's transaction returns 404**, not a redacted 200 —
  and the identical call succeeds for an owned row;
* a tampered session token is rejected, and a raw customer id cannot be used as
  a selector;
* a review cannot be opened over a foreign transaction;
* each filter does what it claims (`no_merchant` really returns only rows with a
  null merchant; `next_day` really returns only rows whose event date follows its
  process date; unknown-direction rows never receive a sign);
* a rule that matched nothing is reported as *clear* rather than omitted;
* the review record hard-codes every "did not happen" field to false, keeps the
  customer's words out of the verified facts, and carries a 64-character digest;
* the CSV export carries both date bases and no fraud column.

Small source regressions are separate from that published-snapshot acceptance:

```bash
python3 -m venv .venv-test
.venv-test/bin/python -m pip install -r requirements-test.txt
.venv-test/bin/python -m pip check
.venv-test/bin/python -m pytest -q tests
```

On Windows, use `.venv-test\Scripts\python.exe` for the same commands. The
tests write a tiny synthetic Parquet fixture under the test runner's temporary
directory; they do not open `/banking-data`, install through the launcher or
start a server. They cover ownership refusal, preserving an existing artifact
on failed rebuild/verification, the precise 72-hour boundary, nullable source
balances, profile isolation, explicit projection and truthful local review
records. Launcher tests mock their tools and verify failure propagation and the
configured serving path; run them on both Windows and Linux to cover each
launcher. These checks do not establish published-snapshot or runtime acceptance.

## Honest limits

* Not a bank. Nothing here moves money, opens a dispute, issues a refund or
  reaches an agent.
* Not an authentication system. The profile picker is a demo selector; the
  isolation it enforces between profiles is real and tested, but it is not a
  login.
* Names shown are aliases over real snapshot customer records. The underlying
  identifiers never leave the server.
* Balances are the snapshot's own values. They are never recomputed by summing
  transactions. A currency/category total is unknown if any contributing
  product balance is missing; available credit is unknown without both its
  source balance and source limit. Missing data is never rendered as zero.
* The snapshot contains 24 distinct merchant names in total. The merchant-level
  views are therefore thin by nature, and the app says so rather than padding
  them.
* `--api-only` skips the client build; an already-built client may still be
  served. The React build needs Node 20+.
