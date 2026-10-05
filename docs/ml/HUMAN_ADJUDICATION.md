# Independent human routing review

The [blank review worksheet](../review/human-adjudication-template.csv) contains the exact 120 frozen synthetic utterances, case numbers and language, with **no model predictions or AI-proposed labels**. It is a review aid, not completed human evidence. The frozen CSV and its original hashes remain unchanged.

An independent reviewer should label each case `inquiry`, `dispute`, `human` or `other` using the [published label protocol](router_holdout_provenance.md#label-protocol), then record their name/identifier, confidence and ambiguity notes. Avoid reading model predictions, error tables or the original proposed labels before completing the worksheet. Reviewers need not receive training examples.

For overlap, asserted immediate security risk, an explicit person request, legal threat or vulnerability takes precedence. Otherwise an asserted transaction problem is `dispute`; a neutral own-account factual request is `inquiry`; other requests are `other`. Negated incidents and educational questions require their full context rather than isolated keywords.

Have a second reviewer independently inspect disputed or low-confidence cases. Preserve both original worksheets, reviewer timestamps and disagreements. Publish agreement counts and a separately versioned adjudicated CSV and hash; do not replace the frozen AI-authored diagnostic. Report results both against original proposed labels and the adjudicated labels, including which decisions changed and why.

This procedure can adjudicate the existing diagnostic's label reliability. Because its outcomes have already been inspected, it cannot make this workload an untouched prospective test. Further model/prompt/threshold development requires a new frozen evaluation set, created and adjudicated independently before the next experiment. No pending worksheet, AI reviewer or test pass should be described as completed human adjudication.
