# Persistent local Dispute demo

This runs the actual Savia UI and application Motor against a newly isolated native FLUJO worker. Its banking data and historical coverage are explicitly authored fixtures, not organizer or production history. Intake creates durable simulated `CMP-SBX` receipts; it performs no real-bank action.

The root coordinator owns this runtime. Existing apps, avatar previews, CI workers, and Fly production remain independent.

From the committed demo worktree, prepare the public Git-only application overlay:

```powershell
./deploy/local-dispute/start.ps1 -Image 'registry.fly.io/flujo-factored-2026@sha256:ACTUAL_DIGEST'
```

After the shared resource handoff and image qualification, add `-Start`. The script limits the new container to 2GiB, two CPUs, and 512 PIDs; it admits it only with at least 6GiB free physical memory and 16GiB available commit. Linux CI retains its separate unchanged 8GiB guard. The nested Bubblewrap namespace requires the container seccomp option, while the native wrapper still independently restricts filesystem, environment, credentials, tools, and invocation paths.

Docker publishes only `http://127.0.0.1:43900`. The worker remains internal. The frontend uses that exact origin and loopback cookies. Bank/app UID10001 owns private fixture state and signing material; worker UID1000 receives read-only admission controls through group10002. No production ledger or old capability is imported.

The dedicated named volume retains fixture configuration, bank/workflow/frontend history, admissions, and revocations. Restart the same owned container or recreate its stopped container with this script; never generate another fixture over retained state. Retrieve the demo access code privately from `/data/local-demo` after preparation. Runtime logs do not print the code or private records.

An open page or healthy worker is not acceptance. Verify actual browser login and owned selection, real native stages without fallback, explicit prepare/consent/confirm, persisted verified receipt, native receipt follow-up, replay/owner denial, logout revocation, and restart readback. Record the image digest, public overlay revision, compiled native/UI source identities, and observed receipts separately.
