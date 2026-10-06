Prepared successor helpers; preparation is not live acceptance.

Source: c44d416fcf1ab95bcb16c77651418e6570d79782
Tree: fabf02d622f51302e229137405e3607356d00ab0
Context: C:/Users/Moe/.codex/tmp/savia-ui-runtime-c44d416fcf1a
Descriptor SHA: 3d200c1f58957b3b3a032dbde642633e6c34eee70c7bee26734cdf0e1d137dd9
Current accepted image: registry.fly.io/savia-rc-2026@sha256:44bc554cd82ad62db51d536d580df248cbb188d24732e7ec1ed8133617c632a0
Source183, fresh browser21 (old22 removed by build-layer verifier), retained native4,
unchanged portal634/28, unchanged pitch12 and media16, critical server6219 bytes.

Use Python3.13 and existing installed httpx; use existing Node/Playwright/MS Edge.
No dependency installation is performed by these helpers. There is no build command.
No helper may be copied into the Docker public context with private config/binding files.

Future root-reviewed order, after all five frozen5c reviews and PR86 CI/source/build
integrity qualification are complete. Replace IMAGE with the exact immutable built
registry.fly.io/savia-rc-2026@sha256:<64hex> image; tags are rejected.
Use the full absolute script paths below or work in this helper directory.

1. Capture actual complete currently44bc config privately, without changing machine:
   python promote_successor.py capture --descriptor-sha 3d200c1f58957b3b3a032dbde642633e6c34eee70c7bee26734cdf0e1d137dd9 --root-go --frozen-cohort-complete
   Default private snapshot: C:/Users/Moe/.codex/tmp/savia-ack-successor-private-c44d416fcf1a/accepted-44bc-machine.private.json
   This must match the complete preserved baseline except image. No output contains env/config secrets.

2. Image-only promotion, exact full current config must equal captured44bc config:
   python promote_successor.py promote --image IMAGE --descriptor-sha 3d200c1f58957b3b3a032dbde642633e6c34eee70c7bee26734cdf0e1d137dd9 --root-go --frozen-cohort-complete
   New private before/config/output/after files use successor names. No retry or automatic rollback.
   Full post-update config is compared with image-only expected config before preservation is claimed.

3. Independently verify actual image/source/fresh UI/native/portal/server/config bytes:
   python qualify_runtime.py --image IMAGE --descriptor-sha 3d200c1f58957b3b3a032dbde642633e6c34eee70c7bee26734cdf0e1d137dd9 --root-go --frozen-cohort-complete
   This invokes the exact hash-pinned in-image AFTER guard; complete UI inventory must be exactly21.
   It writes a sanitized runtime-verification.json with browser_source=c44 and portal_source=634.

4. Verify unchanged public portal27 HTTP assets, health/gateway/anonymous/internal guards:
   python verify_public_assets.py --image IMAGE --descriptor-sha 3d200c1f58957b3b3a032dbde642633e6c34eee70c7bee26734cdf0e1d137dd9 --root-go --frozen-cohort-complete

5. Prepare a new private binding from fresh proofs and actual existing private credentials:
   python prepare_native_binding.py --image IMAGE --credentials C:/Users/Moe/.codex/tmp/savia-native-live-binding.private.json --descriptor-sha 3d200c1f58957b3b3a032dbde642633e6c34eee70c7bee26734cdf0e1d137dd9 --root-go --frozen-cohort-complete
   Old source/image/GO from the credential file are never reused; only actual code/gateway fields.
   New default binding: C:/Users/Moe/.codex/tmp/savia-ack-successor-private-c44d416fcf1a/native-binding.private.json
   Complete runtime/source/UI/native/portal maps and successful health/HTTP proof are required.

6. Read-only existing blocked-card/saved-receipt continuity (12 HTTP checks, zero providers/writes):
   node card_continuity.mjs C:/Users/Moe/.codex/tmp/savia-ack-successor-private-c44d416fcf1a/native-binding.private.json
   Saved receipts are compared to a local immutable c44 copy of the dated predecessor public receipt.

7. Only after future explicit root GO, bounded actual ES/PT product-UI native workload:
   node native_live.mjs --execute C:/Users/Moe/.codex/tmp/savia-ack-successor-private-c44d416fcf1a/native-binding.private.json
   Optional third argument must be a fresh child of
   C:/Users/Moe/.codex/tmp/savia-ack-successor-native-private-c44d416fcf1a
   Two positive provider-eligible turns maximum/required on success, two product UI exact ACKs,
   two tampered registered-result HTTP409 checks (provider-ineligible), zero card writes,
   unchanged zero-PCM fake microphone, no ASR/worker utterance/voice-speak/analytics.
   Login contexts are unrecorded; storage state stays in memory; captures remain private.
   Binding rejects old browser maps, altered helper bytes and runtime proof older than15 minutes.
   Asset responses reject unknown or mismatched fresh-UI assets, rather than silently accepting them.

Read-only preparation commands:
   python -m unittest discover -s C:/Users/Moe/.codex/tmp/savia-ack-successor-qualification -p test_helpers.py -v
   node --test C:/Users/Moe/.codex/tmp/savia-ack-successor-qualification/test_binding_gate.mjs
   node --check native_live.mjs
   node native_live.mjs --describe

Limits: all receipt outputs use create-new semantics. Do not reuse/overwrite a prior attempt.
If proof becomes stale or an invocation fails, inspect it and re-plan a fresh explicitly approved
attempt; these helpers do not automatically retry provider calls, uncertain ACKs or promotion.
The original workload validates fresh browser playback with unchanged native server, not live
503/network ACK-recovery injection. Offline148/148 coverage qualifies the recovery cases.
Matching a provider caption does not prove waveform/text alignment or physical hearing.
No new acceptance, health, preservation or playback flag exists until its actual future check passes.

Offline preparation checks completed:6 Python tests and5 Node tests passed; all Python AST
and Node syntax checks passed. These runs used mocks/local reads only, zero network/provider.
