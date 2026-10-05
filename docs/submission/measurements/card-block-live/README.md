# Immediate card protection — live successor acceptance

**Two actual public API customer journeys passed**, Spanish with the Mexico
fictional profile and Portuguese with the Colombia fictional profile, on
October 5, 2026, 21:57:56–21:58:42 UTC (16:57:56–16:58:42 Bogotá).

The [public Savia demo](https://savia-rc-2026.fly.dev) now supports owned card
selection, explicit confirmation and durable simulated protection. The
[submission portal](https://savia-rc-2026.fly.dev/submission/) is public before
the fictional-profile login.

The [actual API receipt](api-receipt.json) records every HTTP step. Both journeys
verify: asking opens the card flow; preparation leaves status unchanged; omitted
consent returns 422; explicit consent returns a verified simulated blocked
receipt; readback and repeated confirmation return the same receipt; overview
shows the block; a fresh login recovers it; another profile cannot read or confirm
the card. Unauthenticated application access returns 401.

The [deployment receipt](deployment-receipt.json) pins:

- Application source: `f3c57b26d07c1e96b6e61a25befcbbc5fd51a17f`.
- Image: `registry.fly.io/savia-rc-2026@sha256:c38f3af736defdf55c7de47b0e1597ad361b3f748c845176b920377fd12b307f`.
- Exact retained native base: `sha256:35903f9a1ea70f8b3c589d5680ed50307efd34870ce004bdd1833b9029b6dc93`.
- Existing machine, persistent volume, environment, guest resources, services,
  entrypoint and restart configuration preserved.

The [runtime verification](runtime-verification.json) verifies all **177 exported
source files** against their committed hashes. It separately records actual
served browser asset hashes and retained native bootstrap/controller/package
lock/build identifiers. A fresh reviewer independently matched **22 served UI
files plus all 27 public portal artifacts** against exact SHA-256 values.

Additional local Linux acceptance used the immutable deployed application source,
a disposable container running UID/GID 1000, and the corrected private-directory
test fixture: **33 card API/retained-transition tests passed**. The earlier CI
failure correctly refused a fixture's insecure state directory; production's
launcher already sets umask 077. Later repository changes to that test and these
reports do not relabel the deployed application source.

This is authenticated API/host/ledger acceptance over fictional data. It is not
a graphical browser recording, a voice quality test, a real bank block, or
acceptance of the expanded collaborative fleet. The original frozen release
tags and recorded customer successes retain their historical source pins.
