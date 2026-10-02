# Native voice with backend text context

Read-only source review, 1 October 2026. No weights were downloaded, GPU job
dispatched, account changed or production provider switched during this review.
This document changes no release gate.

**Neither reviewed open-weight runtime exposes a verified, supported text-result
injection API inside its ongoing full-duplex audio session.** MiniCPM-o 4.5 has
genuine duplex audio/video, but its text-message API is a separate turn mode.
Qwen3-Omni accepts text plus native speech generation, but its documented
open-weight serving interface uses complete chat requests. A supported live
function-result channel does exist in the separately hosted Qwen-Omni-Realtime
service; that service must not be conflated with the open-weight checkpoint.

## Comparison

| Candidate | Native interaction | Text/context contract | Hardware and license |
| --- | --- | --- | --- |
| `openbmb/MiniCPM-o-4_5` | Simultaneous audio/video input and text/speech output; autonomous listen/speak decisions | Duplex prefill takes audio and optional frames. Initial system prompt is supported; a later text/tool-result item is not exposed by the reviewed duplex API. | 9B model, Apache-2.0 code and weights. Official PyTorch demo requires Linux and over 28 GB NVIDIA VRAM; approximately 21.5 GB after initialization. |
| `Qwen/Qwen3-Omni-30B-A3B-Instruct` | Integrated Thinker–Talker speech; text, audio, image and video input; streamed text/audio output | Complete `messages` prompt per generation. Official audio-function example produces tool-call text with audio disabled; it does not show a live result continuation. | Apache-2.0. Official BF16/FlashAttention2 example needs 78.85 GB for 15 seconds of video, rising with input length. This is not an audio-only minimum. |
| Hosted `qwen3.8-omni-flash-realtime` | Documented native full-duplex WebSocket/WebRTC with audio/video | Explicit function call → textual `function_call_output` → native spoken continuation in the same session | Regional Model Studio API key and workspace required. Hosted terms/pricing apply; no self-hostable weights/runtime were established for this specific service model. |

Sources: [MiniCPM model card](https://huggingface.co/openbmb/MiniCPM-o-4_5),
[official demo requirements](https://github.com/OpenBMB/MiniCPM-o-Demo/blob/47709a9210dfd71afa76c058e017fc8c4db5c8d2/README.md#resource-consumption),
[Qwen checkpoint](https://huggingface.co/Qwen/Qwen3-Omni-30B-A3B-Instruct),
[Qwen memory table](https://github.com/QwenLM/Qwen3-Omni/blob/e4235853125589c789f06a2dd83e9f4126df5e9d/README.md#minimum-gpu-memory-requirements),
[hosted realtime contract](https://www.alibabacloud.com/help/en/model-studio/realtime).

## MiniCPM-o: the two prefill methods are different

4.5 was released on 3 February 2026. It supports English/Chinese speech,
reference-voice conditioning and continuous video; the official demo processes
approximately one-second input units. The published A100 per-unit figures are
about 0.9 seconds normally or 0.5 seconds with compilation. Those are publisher
measurements, not avatar latency measurements.
[Release record](https://github.com/OpenBMB/MiniCPM-V#news),
[duplex architecture](https://github.com/OpenBMB/MiniCPM-o-Demo/blob/47709a9210dfd71afa76c058e017fc8c4db5c8d2/docs/en/architecture/duplex.md).

The decisive source signatures are:

```python
# Simplex / turn mode: text can extend its existing session cache.
model.streaming_prefill(session_id, msgs, ...)
# Duplex mode: no text/messages/tool-result parameter.
model.duplex_prefill(audio_waveform=None, frame_list=None, max_slice_nums=1)
```

The first accepts one message with role `system`, `user` or `assistant`, including
string content. A stable session ID retains its LLM cache; a new ID resets it.
The duplex path instead uses `DuplexCapability` and its `StreamDecoder`.
`duplex_prepare` clears streaming state and calls `decoder.reset()` before
prefilling the initial prompt. Calling it again to add Savia's reply therefore
does not preserve the ongoing session. Directly feeding decoder embeddings would
be an unsupported source modification requiring training/behavior qualification.
[Pinned implementation, simplex L3418 and duplex L3935/L4461/L4560](https://github.com/OpenBMB/MiniCPM-o-Demo/blob/47709a9210dfd71afa76c058e017fc8c4db5c8d2/MiniCPMO45/modeling_minicpmo_unified.py#L3418).

The public `wss://host/v1/realtime?mode=audio` protocol also only documents audio
for `input.append`; prompt/instructions arrive in `session.init`. Text `messages`
are available in `mode=chat`, explicitly described as turn-based. An open socket
does not make that mode duplex. There is no reviewed native tool/result schema
or exact-pronunciation guarantee.
[Audio protocol](https://github.com/OpenBMB/MiniCPM-o-Demo/blob/47709a9210dfd71afa76c058e017fc8c4db5c8d2/docs-app/content/docs/en/realtime-api/audio.md),
[chat protocol](https://github.com/OpenBMB/MiniCPM-o-Demo/blob/47709a9210dfd71afa76c058e017fc8c4db5c8d2/docs-app/content/docs/en/realtime-api/chat.md).

## Qwen3-Omni: native speech, request-based open serving

The open Instruct checkpoint supports Spanish/Portuguese speech input and output
and three supplied voices. Its official web demo rebuilds conversation messages
and invokes `model.generate(**inputs)` for each prediction. The audio-function
notebook sets `RETURN_AUDIO=False`, requests XML tool calls, and never appends a
tool result or resumes live audio. It establishes tool-call text generation only.
[Audited demo](https://github.com/QwenLM/Qwen3-Omni/blob/e4235853125589c789f06a2dd83e9f4126df5e9d/web_demo.py#L181),
[audio-function notebook](https://github.com/QwenLM/Qwen3-Omni/blob/e4235853125589c789f06a2dd83e9f4126df5e9d/cookbooks/audio_function_call.ipynb).

Current vLLM-Omni documents native streaming text/audio from
`POST /v1/chat/completions`, using `messages` and `modalities:["text","audio"]`.
It can accept a new prompt containing a backend result, which is a useful
turn-based native option. Neither that documentation nor the audited demo exposes
a live input/result mutation channel for an already generating request. Persistent
worker residency or prefix caching must not be treated as continuous duplex state.
This is an API evidence limit, not a proof that the architecture cannot be adapted.
[Official vLLM-Omni serving](https://docs.vllm.ai/projects/vllm-omni/en/latest/user_guide/examples/online_serving/qwen3_omni/).

## Hosted Qwen has the explicit result channel

Alibaba's English documentation, updated 29 September 2026, identifies
`qwen3.8-omni-flash-realtime`. A model tool event supplies a `call_id`; the client
can return actual public backend output as text:

```json
{
  "type": "conversation.item.create",
  "item": {"type": "function_call_output", "call_id": "provider-call-id", "output": "Actual public backend result"}
}
```

After the tool-call response finishes, send one `response.create` for the native
audio/text continuation. This is a documented mid-session result path, not a
separate STT→text→TTS chain. VAD mode permits continued input during output and
provider interruption. Function-call responses themselves contain arguments
without speech; no Gemini-style `WHEN_IDLE` background-speech scheduling was
established. Exact names, numbers and absence of invented continuation still need
listening/grounding tests. Arbitrary unsolicited context insertion should not be
assumed from this correlated function-result contract.
[Realtime function calling](https://www.alibabacloud.com/help/en/model-studio/qwen-function-calling),
[client events](https://www.alibabacloud.com/help/en/model-studio/client-events),
[SDK interruption semantics](https://www.alibabacloud.com/help/en/model-studio/omni-realtime-java-sdk).

The practical inference is to retain the accepted PersonaPlex basic voice work
and its separate bank-narration gate. MiniCPM-o warrants a future audio/video
audition, but its stock duplex API does not resolve the text-result gap. Qwen3's
open checkpoint resolves text-conditioned native turns, while hosted Qwen
provides the supported live tool-result API if a separate provider is later chosen.
None of these source findings establishes a working joined avatar session.
