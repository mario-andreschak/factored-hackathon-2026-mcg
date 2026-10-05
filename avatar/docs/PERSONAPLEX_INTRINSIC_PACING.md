# Closed synthetic speech with intrinsic pacing

`experiments/personaplex_intrinsic_result.py` now prepares v4, anchoring its first
approved word. Two v3 attempts failed; neither qualified audio or made an ASR
request. The diagnosed retry reached 89 frames: its silent drain passed, then
64 native text steps remained padding without starting a reply. This supports a
missing response trigger on silence. The v4 anchor is a separate hypothesis,
independently reviewed with 24 focused local tests; it tests one fixed sentence:

> The payment amount is forty two dollars and seventeen cents. There is no open dispute. No action was taken.

The previous explicit PAD schedule preserved exact text IDs but its actual
audio changed “amount” and “open dispute” and included a clipped opening.
Exact IDs and a closed output window are insufficient evidence of speech accuracy.
Bank-result narration remains disabled in the production native worker.

## Source-bound algorithm

Moshi Appendix C describes preserving the model's sampled PAD/EPAD between
words and replacing its next lexical proposal with the next approved word;
pieces within that word are contiguous. This experiment follows that timing
policy after forcing exactly the first approved word to start a response. That
v4 anchor is an experimental addition, not a published pronunciation guarantee.
It does not copy the paper's separately trained TTS model or change the
dialogue checkpoint's audio delay. [Moshi paper, Appendix C](https://arxiv.org/html/2410.00037v2#S0.SS3)

The pinned `LMGen.process_transformer_output` samples text before its depth-audio
generation. A per-instance hook samples once with the native text settings,
selects the approved token, then passes one-hot logits to the unchanged method
with text-only greedy sampling. Its native audio temperature, top-k, sampler and
cache remain unchanged. Text delay zero makes the current ring-cache slot the
input ledger; the returned text is verified against that ledger at `max_delay`.
These checks fail if the pinned method signature or supported mode changes.
[Pinned NVIDIA LMGen](https://github.com/NVIDIA/personaplex/blob/3428dfd95309a7f3c84fd93259ded0f810d1ff91/moshi/moshi/models/lm.py),
[pinned sampler](https://github.com/NVIDIA/personaplex/blob/3428dfd95309a7f3c84fd93259ded0f810d1ff91/moshi/moshi/utils/sampling.py)

## Audio gate and bounds

The model starts fresh with the qualified NATM1 preset. There is no free
conversation or public-fixture prelude before the sentence. Decoded native
silent agent codes and PAD run on the same continuous cache for at least 25
frames. The gate remains closed until eight consecutive frames have RMS below
0.006; failure to reach that boundary within 50 frames stops the experiment.

The first approved word is anchored, with all of its pieces contiguous. Native
padding then determines when every subsequent approved word begins.
After its first approved token the reply clock has a 256-frame bound. Once all
approved lexical pieces have been selected, further lexical proposals become
PAD while sampled PAD/EPAD remain unchanged. Tail measurement begins strictly
after the final delay-aligned lexical output, then requires at least eight
consecutive quiet frames within a 64-frame tail bound. This is measured audio
quietness, not an assertion that token delay equals phoneme completion.

Only ledger-verified reply/tail output can leave the gate. It closes permanently
before twelve seconds of the fixed NVIDIA public fixture continue through the
same model cache. That later audio and text cannot reopen it. Full native output,
discarded continuation and sampling decisions are saved separately for private
audit, while the caption explicitly identifies a synthetic plan rather than ASR.

Input/output are mono PCM16 at 24 kHz, 1,920 samples per 80-ms frame. The total
clock is bounded to 600 frames/48 seconds. The subprocess covering offline
asset verification, model loading, prompt and inference has a 360-second limit.
One source-backed A100-80GB Function has a 600-second runtime, 60-second startup,
maximum one single-use container, no retries and no warm pool. The client has a
675-second deadline and cancels the admitted input/container in `finally`.

The image is a source-only overlay on the existing private pinned cache.
There is no HF credential, weight download, cache rebuild, browser endpoint,
task API or banking data in this experiment. No caller-selected sentence,
model URL, role or audio path is accepted. Outputs live only under ignored
`avatar/.local/personaplex-intrinsic-result/` with restricted permissions.

## Local review and later qualification

From the repository root, these commands are local and spend no compute:

```powershell
python avatar/experiments/personaplex_intrinsic_result.py --plan
python -m unittest discover -s avatar/experiments -p test_personaplex_intrinsic_result.py -v
```

Twenty-four focused cases pass. They include native padding, the bounded first
word anchor, stalled-later-word failure, delay-aligned first output, contiguous lexical
pieces, sampler restoration on failure, whole continuous clocks with delays
1/2/16, silent drain, a tail measured after the last lexical output, permanent
suppression of later conversation, changed-cache/token rejection, source-only
image bounds, staged-source imports, fixed worker-failure receipts and
synthetic-ASR scope. The diagnostic v3 source family passed 103 cases before the
two anchor cases were added. These are
local source/lifecycle tests; no model pronunciation or successful GPU acceptance
has occurred for this algorithm.

The October 1 attempt exited during `intrinsic_inference`. Its wrapper originally
captured child output and replaced every child failure with a generic RuntimeError,
so the underlying cause was not retained. Stored Modal logs supplied no child
traceback or milestone; the exact app was observed stopped with zero tasks.
The ignored historical failure receipt records that uncertainty. The runner now
returns a fixed worker phase, error class, policy reason code when recognized,
completed frame count and bounded last-frame RMS. It projects no raw stderr,
prompt, provider URL or credential, rejects malformed receipt fields and saves
failures locally. This fixes diagnosis, without changing the model/audio gates
or introducing an automatic retry. The explicit diagnostic retry subsequently
returned `reply_start_deadline`, 89 frames and last-frame RMS0.0002204; its exact
app was observed stopped with zero tasks. A subsequent bounded v4 run anchored
the first word but failed `reply_clock_deadline` after 282 frames, with last-frame
RMS0.0002222. It did not produce a complete qualified reply or call ASR. Native
padding after the anchor did not complete the sentence within the fixed bound;
that observation does not identify all emitted words or prove pronunciation.
No production narration was enabled and no automatic retry was introduced.

After source review, one separately invoked qualification would use:

```powershell
python avatar/experiments/personaplex_intrinsic_result.py --execute
```

The result still requires human listening and one independent transcription
before a speech-accuracy conclusion. The separate `--verify-asr <output-dir>`
mode accepts only completed, hashed, bounded output from this experiment. It
validates those artifacts before reading the existing OpenRouter key and sends
one fixed Whisper request; it never changes the live voice provider. There is
no automatic ASR or paid retry. Missing/changed words, names, amounts, prelude
phonemes, extra promises or a clipped tail fail qualification even when all
approved lexical IDs match. One synthetic pass would justify further isolated
testing, not arbitrary banking narration in production.
