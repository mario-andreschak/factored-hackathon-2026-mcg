# Native card admission: offline qualification

The narrow Savia fix adds `bloquear|bloquea|bloquee|bloqueie` to the existing native voice action pattern. This bundle preserves the captured local regression evidence; it does not establish CI, provider, browser/UI, live-path or deployment acceptance. Card actions still require an owned selection, explicit confirmation and independent receipt verification.

Baseline production commit: `582a4bf2ac332ad09039945400bbd7d20b05a170`. Fix code commit: `67bdb975be17bb41437a073c6ace65bc6c398035`. Historical frozen candidate HEAD: `b13cd3f24f624969484b28f1acceca085cf858eb`. Final frozen candidate HEAD: `f2fa597a481a87b5301531cf180f8f61d1f3ba70` (tree `1638e0be90b1046bbada1972b6ace1ee62a8e4fa`). Full tree/blob/file hashes and commands are in [receipt.json](receipt.json); the captured Python/dependency versions are in [environment.json](environment.json). The tests ran in the working tree before the fix commit. Subsequent byte checks bind the tested source/test copies to the fix commit, historical freeze and final freeze; this is not a claim that CI or a candidate image was tested.

| Captured run | Pytest result | JUnit denominator |
| --- | --- | --- |
| Baseline production plus augmented regression fixture | 14 failed, 68 passed, 81 deselected | 82 selected cases |
| Fixed voice suite | 163 passed | 163 cases |
| Fixed card and card API suites | 20 passed | 20 cases |
| Fixed controller/action/chat/API suites | 136 passed; 112 subtests passed | 136 testcase elements; suite count 248 including subtests |

These are separate denominators. In `actions.xml`, there are 136 actual `<testcase>` elements, the suite `tests` attribute reports 248, and the original stdout reports 112 passing subtests; the XML contains no subtest elements. The baseline is an augmented working-tree test fixture against unchanged committed baseline production code, not a failed run of the baseline commit's original test file. [test_voice.py](test_voice.py) is byte-identical in the baseline and fixed test runs. The 14 failures cover Spanish/Portuguese imperative, formal, want-to-block and polite requests through message/audio; existing question forms and refusal/reported-state/emotional/nonbank controls passed.

Original captured outputs are represented by [baseline-stdout.txt](baseline-stdout.txt), [voice-stdout.txt](voice-stdout.txt), [card-stdout.txt](card-stdout.txt), and [actions-stdout.txt](actions-stdout.txt), with corresponding XML files. Source copies are [baseline-conversation.py](baseline-conversation.py), [conversation.py](conversation.py), and [test_voice.py](test_voice.py); [patch.diff](patch.diff) preserves the exact tested patch. The tests use scripted transports and fictional data; no provider/network calls were made.

For public XML derivatives, exactly one `hostname="..."` attribute and its preceding whitespace were deleted from each original XML using byte regex `\shostname="[^"]*"`. No XML was reserialized; test names, failures, counts, timings, timestamps and other bytes are retained. There were no identifying machine temp paths to redact. Stdout, source/test, patch and environment files retain exact original bytes. Original-to-public SHA256s, lengths and transformations are listed per artifact in the receipt. Original stdout/JUnit remain private and unchanged.

Saved source/test files use exact LF Git blob bytes, with zero CRLF sequences. Their original bytes are preserved here and match the qualified Git blobs and frozen working-tree files exactly; no normalization was necessary. The receipt records the original SHA256s and Git blob IDs/SHA256s. No source copy was rewritten. The original private output destinations in recorded commands are represented by `<private-...-output>`; only their path is withheld.

Final source qualification adds the required generated graph source-hash refresh at `f2fa597a481a87b5301531cf180f8f61d1f3ba70`. The captured fixed source/test bytes remain unchanged. The graph SHA256 is `43fd857863961f4d87d62b85c9a25ae261b59aa2e74d14c8b3e7cf8406a41d03`; its only byte change from the historical freeze is the protected `conversation.py` hash from `6032...` to `c978...`. All 89 protected source hashes match the final working tree. Root reported 11 graph tests and 89 subtests passing through its tool response; that observation has no original stdout/JUnit in this bundle. No graph test rerun or raw log is claimed here. Actual final-source CI qualification remains separate.

[SHA256SUMS.txt](SHA256SUMS.txt) hashes every other public bundle file. This bundle contains no private runtime configuration, storage, screenshots or live credentials; provider-key literals in the exact test source are scripted mock fixture identifiers.
