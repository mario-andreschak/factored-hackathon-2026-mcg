# Self-hosted native voice assessment

Reviewed 1 October 2026. PersonaPlex is now an explicitly selected Game candidate
with a locally qualified raw-PCM worker/relay implementation and a passed bounded
actual-provider browser audition using public prerecorded microphone audio.
Physical microphone/AEC and natural human conversation remain unqualified. The research and preparation created no payment
method or model-license acceptance. The owner separately cleared model access and
authorized a bounded Modal offline audition. The corrected audition completed;
the browser component's native-provider tests remain separate from that result.

## Practical choice

PersonaPlex is the closer open-weight fit for the three characters: native
full-duplex speech with a text role prompt and voice conditioning. Stock Moshi is
also native full-duplex, but changing its character/voice requires fine-tuning
according to its own FAQ. A Whisper transcription server alone cannot supply
native conversational audio; adding separate text and speech models recreates
the pipeline the user rejected.

The current qualification target is **PersonaPlex on one Linux A100 80 GB
GPU**, one admitted conversation at a time, through the game's private same-origin
raw-PCM relay. This GPU choice is an engineering recommendation for
headroom, not a comparative benchmark: NVIDIA's model card lists A100/H100 support,
and the bounded audition now confirms loading and inference on A100 80 GB. The native model is distinct from the stronger
Savia workflow model; bank facts and actions must remain behind Savia.

Hosting access and hardware require verification. Modal's current billing
documentation requires a payment method. Its $30/month Starter compute allowance
does not make a new account a cardless alternative to Google. Root's read-only
browser review found an authenticated existing Starter workspace with available
compute credit; a bounded voice-only offline smoke has now completed separately.
It does not establish a live browser conversation. Blender and artwork generation
stay local. The local machine was inspected
with a read-only GPU query: **RTX 2070 SUPER, 8 GB VRAM**. It does not meet Moshi's
documented 24 GB PyTorch requirement. PersonaPlex offers CPU offload, but that is
not evidence of usable conversational latency on this machine. An unofficial
quantized port is an experiment requiring separate quality/runtime qualification.
[Modal billing](https://modal.com/docs/guide/billing),
[Moshi requirements](https://github.com/kyutai-labs/moshi),
[NVIDIA model card](https://huggingface.co/nvidia/personaplex-7b-v1).

## Models and licenses

| Candidate | Verified strengths | Material limits |
| --- | --- | --- |
| NVIDIA PersonaPlex 7B v1 | Native simultaneous listening/speaking; text role plus audio voice conditioning; 18 supplied voice embeddings. Code MIT; weights governed by NVIDIA Open Model License. | English and Linux are the documented configuration; model weights require license acceptance; stock server has no native bank-tool/result protocol. |
| Kyutai Moshi | Native full-duplex speech/text framework with Mimi streaming codec; PyTorch, Rust/Candle and Apple MLX backends. Code Apache 2.0/MIT; weights CC-BY 4.0. | Stock model is English; role/voice customization requires fine-tuning; documented PyTorch GPU requirement is 24 GB; Windows is not officially supported. |

PersonaPlex's official model card describes English input/output and Linux
A100/H100 hardware. Its Hugging Face model requires license acceptance and a
server-held download token. Neither model's existence establishes ES/PT quality,
financial grounding, instruction fidelity or backend tool orchestration. Use the
actual release license/attribution requirements when packaging a deployment.
[PersonaPlex README](https://github.com/NVIDIA/personaplex),
[PersonaPlex model card](https://huggingface.co/nvidia/personaplex-7b-v1),
[Moshi README](https://github.com/kyutai-labs/moshi),
[Moshi FAQ](https://github.com/kyutai-labs/moshi/blob/main/FAQ.md).

## Modal deployment feasibility

Modal supports GPU web servers and WebSockets. Its documented decorators can
serve a stock `aiohttp` process on a fixed container port; each WebSocket keeps a
function invocation alive. A persistent model-cache Volume would avoid repeated
weight downloads. Cold-start loading and model warmup occur before the session is
usable; a warm container reduces waiting while consuming billed GPU resources.
[WebSocket hosting](https://modal.com/docs/guide/webhooks#websockets),
[cold starts](https://modal.com/docs/guide/cold-start).

The current official `modal-examples` repository tree was inspected. It includes
streaming/batched Whisper examples, but no PersonaPlex or Moshi deployment example.
Modal's Quillman voice app is a different architecture and does not prove native
PersonaPlex acceptance. This proposed port therefore needs its own image,
readiness, authentication, disconnect and cost tests.
[Official examples](https://github.com/modal-labs/modal-examples),
[Quillman](https://github.com/modal-labs/quillman).

Current GPU task prices are approximately A100 40 GB **$2.10/hour**, A100 80 GB
**$2.50/hour**, A10 **$1.10/hour**, and L4 **$0.80/hour**, computed from the published
per-second rates. CPU, memory, region premiums and warm time can add cost. The
cheaper cards are not qualified PersonaPlex configurations here. A $30 allowance
would cover at most about 14 GPU-only A100-40 hours; it is not a production budget.
[Modal pricing](https://modal.com/pricing).

## Avatar adapter work

The stock PersonaPlex server exposes binary WebSocket `/api/chat`. Audio uses
Opus packets with a leading kind byte; output includes generated text tokens.
Role and voice are chosen at session initialization. A shared async lock permits
one active model conversation per stock process. It is not interchangeable with
the Gemini raw-PCM/WebSocket tool protocol.
[Audited server source](https://github.com/NVIDIA/personaplex/blob/main/moshi/moshi/server.py).

The prepared, source-pinned offline audition and its measured result are tracked
in [experiments/README.md](../experiments/README.md). It has no public endpoint,
automatic retries or permanent GPU service. Its local preparation checks are not
evidence of GPU inference or conversational quality. The corrected audition
downloaded its pinned assets in 251.91 seconds, then completed model loading,
inference and normalization in 42.78 seconds on an A100-SXM4-80GB. It produced
20 seconds of valid 24 kHz mono PCM WAV; the public-fixture text identified itself
as Moss and addressed the fixture's cooking question. Peak allocated tensors
used 18.11 GiB, which is narrower than total process/GPU memory. Modal subsequently
showed no live apps or containers and $29.85 remaining from the original $30.
These measurements qualify that offline run only. The user subsequently accepted
general native voice quality for now. Actual browser duplex qualification remains
a separate gate.

A second bounded synthetic forced-speech audition, reported by the experiment
owner, reused cached weights and matched the requested text token IDs. Its mean
model frame time was 51.5 ms, maximum 57 ms, below the codec's 80 ms frame period.
This is a per-frame model measurement, not browser round-trip latency. Once
free continuation resumed, the model invented a reassurance that no action would
be taken. Bank-summary speech therefore remains unqualified: the adapter must
prevent unsupported continuation and preserve Savia's exact public result.
The first NATM1 sample had accent feedback; later approval accepts its current
general voice quality, not three distinct voices or reliable bank pronunciation.

`AVATAR_VOICE_PROVIDER=personaplex` now connects the native hook to Game. The
custom worker handles mono PCM16LE at 24 kHz in both directions, so this path does
not need browser Opus encoding/decoding. Nine local worker checks cover real
aiohttp HTTP/WebSocket transport with a fake model, pinned offline assets,
single admission, frame clocks, interruption generations and teardown. Eight
actual-hook and three actual-Game browser fixtures passed in the pre-observer
complete rerun (42 passes, one optional real-upstream skip). Game cases verify
fixed-role teardown and consumed-lease availability. These checks do not establish
authenticated live Modal microphone transport, acoustic barge-in or latency.

The operator prepares and warms one bounded worker before the user gesture. A
private lease names its fixed Moss, Orbit or Spark role; currently only the
reviewed `NATM1.pt` embedding is permitted. The same-origin relay issues one-use
local tickets and holds the Modal credential outside the browser. One lease can
admit one stream; the game cannot launch a GPU, restart a consumed worker or
change its role mid-session. Typing or selecting an incompatible character ends
native voice and continues in visual preview. The worker's generated text is
assistant captioning, not user ASR; an activity meter does not classify mood.
The optional `AVATAR_BACKGROUND_ASR=openrouter` observer now recognizes completed
utterances externally for user text and intent scenery. It preserves the native
role and does not add model tools or result narration. Its default configuration
submits no bank query. The separate exact `AVATAR_NATIVE_READ_BRIDGE=readonly`
flag can enable an explicit visible owned read with a durable native playback
hold and text-only real result; joined live acceptance remains separate. Both
opt-ins are disabled by default, and recognition pauses around the pond; see
[background recognition](./PERSONAPLEX-BACKGROUND-ASR.md). Its source-unit checks
pass, as do focused bridge/hold checks and the current 93-unit/image boundaries.
The complete current browser rerun passes 64/one optional real-upstream skip.
The separate corrected public rice-request audition now passes one actual
transcription delivered to Game while native PCM continues, followed by mute
and confirmed browser/worker cleanup. It uses no Savia/read bridge. Physical
microphone/echo and broader recognition accuracy remain separate.
See [PERSONAPLEX_RELAY.md](./PERSONAPLEX_RELAY.md) for the exact contract.

The stock model has no `delegate_task`/`WHEN_IDLE` tool protocol or supported
text-result input. The custom worker also rejects text input, result injection
and live persona updates. The relay forwards microphone audio, but forwards no
bank cookie, Savia sign-in values or backend task facts.
The real Workbench can independently perform an authenticated keyboard inquiry
and show its actual reply, as already qualified in a separate read-only check;
that result is not spoken by PersonaPlex. Keep native bank narration disabled
until pronunciation and unsupported continuation are controlled. Source review
of other native runtimes is in [NATIVE-VOICE-CONTEXT.md](./NATIVE-VOICE-CONTEXT.md).

The corrected actual browser/provider audition passed: one admission/WS,
1.520-second readiness, first PCM at 1.769 seconds, one audible VAD barge-in,
129/128-ms VAD acknowledgements and 134-ms manual acknowledgement. Zero clock
errors, a continuous 1.746-second all-zero mute interval, zero surviving browser
audio resources and confirmed worker exit qualify the bounded native transport.
It used public prerecorded microphone audio; the next acoustic acceptance is a
physical microphone/AEC and natural human conversation check. No new bank query
is required. Retain the Gemini/OpenAI adapters and honest
silent preview alongside this explicit candidate. The private Sandbox has a
600-second lifetime including warmup, one admitted caller, no automatic retry
and verified termination. Its current maximum-resource GPU/CPU/RAM estimate is
approximately $0.77 for ten minutes, with CPU image building billed separately;
see the relay's Sandbox-specific calculation. An estimate is not an account
spending cap. A warm production service would have a different cost profile.

## Voice studio projects

The two likely open-source ElevenLabs-style studio references are
[Voicebox](https://github.com/jamiepine/voicebox) (MIT) and
[VoiceStudio](https://github.com/debpalash/VoiceStudio) (AGPL-3.0). They address
voice creation, cloning and text-to-speech workflows. Neither is evidence of a
native simultaneous-listening-and-speaking conversational model, so they do not
replace the PersonaPlex/Moshi runtime qualification. Review the specific engine
and model licenses independently of each studio application's license.
