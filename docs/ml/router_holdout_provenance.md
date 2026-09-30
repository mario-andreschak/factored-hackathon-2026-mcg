# Frozen intent-router diagnostic holdout

## Manifest

| Field | Value |
| --- | --- |
| Current dataset | `ml/data/router_test.csv` (quality-screened v2) |
| Author value on every row | `codex_blind_holdout_20260928` |
| Authorship | AI-authored by a separate Codex subagent assigned only this holdout and provenance note |
| V2 freeze recorded (UTC) | `2026-09-28T23:51:34Z` |
| SHA256 of exact frozen v2 CSV bytes | `3C4F68D880146915D7FB27C7884733190C1D87D84E1FEE6D066AFEED85538684` |
| V2 file size | 12,986 bytes |
| Preserved original dataset | `ml/data/router_test_blind_v1.csv` |
| Original v1 freeze recorded (UTC) | `2026-09-28T23:41:40Z` |
| SHA256 of exact preserved v1 CSV bytes | `D23B67FFFC2A3EF5367452E23FF9C20FE8CB3763942A68DD19860535B05AB303` |
| Original v1 file size | 12,909 bytes |
| Columns, in order | `text,label,lang,author` |
| Total data rows | 120 |
| Unique text values | 120 |
| Human review | **Not human-reviewed or adjudicated yet** |

Each SHA256 identifies the corresponding CSV itself, including its header, encoding, punctuation, and line endings. Neither is a hash of this provenance note. Verify the bytes against this manifest before using or submitting a dataset version.

## Independent authorship

All utterances were composed originally for this assignment from the supplied label protocol. The author did not read any repository training CSV, `build_train.py`, provisional test file, existing evaluation report, or model predictions. No model evaluation or training was run by the author. Validation read only the author's own CSV versions to check schema, counts, exact-text uniqueness, author value, the exact one-row change, and SHA256.

This is independent AI authorship relative to the repository training and evaluation materials, not a claim of human authorship or of independence from the language model's pretraining. The examples are synthetic: they contain no real customer records, credentials, identification numbers, or private data. They were not sampled from production messages.

## Authorized pre-report data hygiene revision

After the original freeze, the coordinating agent conveyed one training-similarity finding from a pre-report data hygiene screen: the generic Portuguese sentence below exceeded the repository's existing character-similarity threshold of 0.8 against train/test material. The repository hygiene requirement is zero overlaps above that threshold. **The finding was conveyed to the author, but no training text, model performance, or model predictions were provided.** The author did not inspect training data or independently run that similarity screen.

The exact original CSV bytes were copied to `ml/data/router_test_blind_v1.csv`, with the original SHA256 verified before and after the copy. An explicitly authorized v2 replaced only this sentence, independently composing a more concrete banking-context request for a person:

| Version | Portuguese utterance |
| --- | --- |
| V1 | Quero falar com um atendente de verdade. |
| V2 | Preciso que uma pessoa do banco me acompanhe na conferência das parcelas de uma compra que aparecem na minha fatura. |

The row remains `human,pt,codex_blind_holdout_20260928`; no other row, field, order, or CSV formatting changed. Both versions contain the same 120-row balanced label/language mix. This was a documented data hygiene correction, not a response to model outcomes. No evaluation or retuning was performed by the author. The v2 author has not verified whether the replacement passes the repository similarity threshold; that is for the coordinating agent's data-quality check. V2 retains original AI-authored labels pending independent human adjudication.

## Count and language mix

| Label | Spanish (`es`) | Portuguese (`pt`) | Total |
| --- | ---: | ---: | ---: |
| `inquiry` | 15 | 15 | 30 |
| `dispute` | 15 | 15 | 30 |
| `human` | 15 | 15 | 30 |
| `other` | 15 | 15 | 30 |
| **Total** | **60** | **60** | **120** |

Spanish includes Mexico-associated conversational forms such as “qué onda,” “ahorita,” and “ya cayó”; Colombia-associated forms such as “parce,” “consignación,” and “extracto”; and Argentina-associated forms such as “che,” “me decís,” “podés,” and “resumen.” These are illustrative regional cues, not exclusive dialect markers or a validated regional sample. Portuguese is intended as natural Brazilian Portuguese and includes Pix, fatura, estorno, colloquial phrasing, and missing accents or typing mistakes.

The set mixes short messages, longer contextual requests, greetings combined with requests, spelling mistakes, and intentionally close label boundaries. Portuguese cases include negated theft, fraud, and agent requests, as well as an educational phishing question. These probe whether an asserted situation and the requested action override isolated keywords.

## Label protocol

- **`inquiry`:** Requests facts about the customer's own account or transactions without asserting a problem. This includes checking balances, transaction status, due dates, an applied fee's detail, or which merchant corresponds to a neutral charge description.
- **`dispute`:** Asserts an unrecognized or incorrect charge, duplicate charge, missing refund, or money deducted but not received. An unrecognized charge alone is a dispute; ongoing unauthorized account access or immediate security danger invokes `human`.
- **`human`:** Explicitly requests an agent or person, or describes an immediate security or fraud risk, lost or stolen card, account takeover, phishing directed at the customer, legal threat, or customer vulnerability. Coercive control or fear of losing access to money is included as vulnerability.
- **`other`:** Falls outside this chosen account/transaction inquiry and dispute support scope: product information, opening an account, branch hours and facilities, general financial education, employment questions, or general conversation.

Resolve overlaps in this order: **asserted security risk, explicit agent request, legal threat, or vulnerability dominates**; otherwise an asserted transaction problem is `dispute`; otherwise an own-account or own-transaction factual request is `inquiry`; remaining cases are `other`.

Question form does not cancel an assertion: asking why a charge happened twice is `dispute`. Neutrally asking which merchant a charge belongs to is `inquiry`. Negated security incidents or negated requests for an agent do not, by themselves, trigger `human`. A general educational phishing question without an asserted incident is `other`. A request for an agent remains `human` even when the same utterance negates theft or asks an ordinary account question.

## Freeze and permitted use

V1 was frozen after creation and structural validation. Its exact bytes remain preserved under the versioned filename above. V2 was separately frozen after the single authorized pre-report hygiene correction and structural validation; the author received no model outcomes and ran no evaluation. Treat both frozen versions as immutable; do not revise, replace, relabel, or append rows in response to model performance. Preserve both hashed versions if human adjudication later produces a separately versioned, documented revision.

This balanced diagnostic workload is **not a prevalence estimate** and is not a random sample of customer traffic. Results on it cannot establish deployment performance, regional coverage, or the frequency of banking intents. Repeated scenario families and cross-language analogues are intentional; exact-text uniqueness alone does not establish semantic diversity.

**Independent human adjudication is required before final submission**, especially for close charge-identification boundaries, negation, legal threats, security urgency, and vulnerability. Until then, labels remain AI-authored proposed ground truth. Record adjudicator decisions and any disagreements independently, retaining this frozen artifact and its manifest.

Do not use this holdout for model tuning, training, threshold or hyperparameter selection, feature design, prompt optimization, or iterative example selection. Evaluate only a previously fixed model and reporting procedure. Any diagnostic inspection of errors must be disclosed and must not be followed by tuning against this same holdout; further development requires a separate untouched evaluation set.
