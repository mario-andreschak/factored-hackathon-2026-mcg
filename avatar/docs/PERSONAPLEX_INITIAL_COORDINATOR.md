# Initial role admission coordinator — isolated source

`server/personaplex-initial.mjs` is an opt-in coordinator, integrated into
`POST /api/avatar/personaplex-initial` behind
`AVATAR_PERSONAPLEX_INITIAL_ROLE=initial`. The flag defaults off; this is not a
new provider deployment. It neither starts a GPU nor writes a lease. Existing
fixed-role v1 behavior is preserved. Local fixtures exercise the
v2 warm → private prime → launcher promotion → private relay grant lifecycle;
they do not qualify microphone capture, native replay, latency or spoken style.

The HTTP route performs the existing exact-origin/CSRF and
gateway checks, resolve the live `avatar_session` object from the server map,
enforce JSON content type, an 800,000-byte body cap, ASR configuration and the
existing rate/concurrency controls, with a 65-second operation/disconnect bound.
The coordinator additionally requires the
operator's `personaplexInitialRole` flag, native PersonaPlex selection and the
explicit OpenRouter background recognizer with a server-side key. Browser
fields cannot select a role, prompt, provider URL, bank identity or task result.

`select(payload, session, {signal, isSessionCurrent})` accepts only the canonical
44-byte-header, mono PCM16 24 kHz WAV produced by `wavFromPcm`, at most twelve
seconds, and an optional two-letter language. It validates a private, fresh,
pinned v2 warm lease and atomically consumes its epoch **before ASR**. Warm
capability requires 207 seconds remaining to leave twelve seconds for capture;
POST reservation requires 195 seconds. ASR is bounded at 45 seconds, one private
prime at fifteen seconds, and matching launcher promotion at three seconds.
There is no retry or reservation transfer after failure, cancellation or an
uncertain response. A fresh operator-owned worker is required to try again.

The existing shared mood classifier selects one static Moss, Orbit or Spark
prompt. Private prime carries only the server-generated opaque selection ID and
role enum. The coordinator verifies the worker's exact phase, selection ID,
static prompt hash, voice and source/model pins, then reads the launcher's lease
until it projects that same immutable tuple. Endpoint, credential, epoch and
original expiry cannot change during this process.

The internal result has two parts: `publicResult` contains `{avatar, transcript,
initialContextDelivered:false}`; `binding` is an opaque in-process object held
in a WeakMap. It cannot survive JSON serialization. Do not serialize the outer
result. The route sends only the ordinary same-origin stream ticket fields plus
the public recognition result, after a private relay grant is verified. Neither
endpoint/token nor epoch, selection ID, audio hash or prompt hash is returned.
Recognition is presentation/history data, not banking authorization,
and the current role-only private prime does not deliver the first problem to
the native model. Future finite native replay must prove that separately.

`claim(binding, session)` consumes the binding before its lease read. It requires
at least 140 seconds remaining: twelve seconds for replay, eight seconds for
connection/READY, and 120 seconds for native use. Thus a slow ASR/prime path may
truthfully fail despite the earlier 195-second floor. The returned private grant
has non-enumerable lease, selected role, session/selection IDs, audio hash,
prompt hash, audio duration, owner AbortSignal and `isValid()` members. JSON or
object spread cannot expose the worker endpoint or token. The relay must check
this grant and the matching v2 disk lease; normal browser fixed-role issuance
must not accept an already primed v2 worker.

Request abort remains linked through selection, claim and response delivery.
Call `acknowledgeDelivery(binding, session)` only after a confirmed HTTP
response `finish`, not merely `res.end()`. Before that point, a disconnect burns
the epoch and invalidates the grant. Afterwards session expiry, session-map
identity loss, `invalidateSession(session)`, `invalidate(binding)` or coordinator
shutdown still abort ownership. Wire relay close/ticket expiry and logout into
these explicit invalidation methods. New speech during selection must abort the
original operation rather than replace or reuse its initial audio.

The first transcript must not trigger the current native bank read bridge or
task hold while selection/replay is pending. Deliver it as scene/history data
only at the agreed native READY boundary. This coordinator performs no account
reads, bank requests, forced narration or financial result speech.

Local source evidence: 27 isolated coordinator cases and sixteen actual local
HTTP/WebSocket route cases pass. They include the exact maximum capture,
origin/session/gateway denials before ASR, owner races, late ignored aborts,
uncertain prime consumption, v2 lease theft rejection, immutable heartbeat
monitoring, 140-second dial and 132-second READY floors, and outer HTTP delivery
cancellation after private prime but before `finish`. The private worker and
ASR are local fixtures; no cloud, model, provider or account request was made.
