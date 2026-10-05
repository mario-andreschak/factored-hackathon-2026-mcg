# Offline generic FLUJO source evidence

Use [the platform guide](../../FLUJO_PLATFORM_EVIDENCE.md) for claims, limits, and the inspection route.

[source-manifest.json](source-manifest.json) identifies 39 unmodified public upstream files (619,009 bytes) from FLUJO commit `0be972ac7b748703d09e407ef96beba45ab17b2a`, tree `5d7116fad792138eb0a6e6adf5a27ff19dc1c0f0`. Each file has an immutable public URL, Git blob ID, SHA-256, and byte count. The [upstream MIT LICENSE](source/LICENSE) is retained with the source subset. The scoped [.gitattributes](.gitattributes) preserves original upstream bytes when this package is committed.

This is a curated inspection subset, not an installable FLUJO distribution. No Savia source or banking adapter is inserted into generic FLUJO. Only selected source and test files were copied; imports outside the subset are intentionally unresolved until a full pinned checkout is supplied.

From this directory, verify source bytes and run the narrow, dependency-free smoke:

```sh
node verify-source.cjs
node verify-source.cjs --git-ref=HEAD
node --experimental-strip-types --require ./offline-preload.cjs ./offline-smoke.mjs
```

The smoke loads the unmodified copied retry-policy module and exercises parsing, bounded retry timing, and cancellation. It was run on Node `v22.13.1` on Windows x64. It does not invoke a model, MCP server, or Savia application. [offline-smoke-results.json](offline-smoke-results.json) records the five passing checks.

To repeat the nine selected upstream unit suites with an already available Git checkout and dependency cache:

```sh
node run-upstream-offline.cjs /path/to/FLUJO /path/to/existing/node_modules /path/to/new-results
```

The runner extracts the immutable Git objects into a fresh temporary directory, checks source hashes, links existing dependencies, and uses upstream Jest configuration with `--runInBand --runTestsByPath`. It never installs or fetches dependencies and removes its fresh temporary checkout after the run. It excludes inherited `.env` files, drops credential-shaped environment variables and private integration selection, and preloads [a network API guard](offline-preload.cjs). The guard is JavaScript instrumentation, not an operating-system sandbox. Selected tests use mocked model, MCP, catalog, storage, and/or dangerous command sinks; inspect the included test files to see each boundary.

[upstream-test-receipt.json](upstream-test-receipt.json), [upstream-tests.json](upstream-tests.json), and [upstream-test-log.txt](upstream-test-log.txt) retain the command, source identity, runtime, package-version comparison, per-test names/results, and output. The recorded run passed 104 tests across nine suites with no guarded network attempts. Eleven installed package versions differ from or are missing relative to the pinned lockfile, including Next `16.3.5` versus locked `16.3.8`; no clean install or transitive integrity audit was performed.

The [examples](examples/) are illustrative ordinary interface payloads for a non-banking release-note digest. Their model/server/tool names are placeholders. They are not execution receipts. Review them with the source contracts and configure matching catalogs before trying them in a separate FLUJO installation.
