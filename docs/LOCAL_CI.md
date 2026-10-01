# CI runs locally

The hourly CI route runs on the developer's Windows computer and disposable
Docker Linux containers. It does not require paid GitHub-hosted runner minutes.
GitHub holds the PR reviews and separately named external CI results. A daily
bounded Modal CPU run at 10:30 America/Bogota is an additional Linux cross-check;
it does not replace Windows coverage.

The avatar development server was stopped after its memory incident. That does
not pause local CI. Preserve unrelated development services and use the reviewed
resource-bounded controller rather than launching uncapped worker commands.

## Complete coverage for one source commit

[The workflow](../.github/workflows/tests.yml) defines eleven jobs: five on
Windows and six on Linux. The private local harness preserves their commands,
environments, checkout pins, independent Python environments and timeouts.

1. Independently review the final source and freeze its full Git commit SHA.
2. Export private committed-source bundles and an immutable workflow manifest.
3. Verify source, bundle, manifest, worker and local Docker image hashes.
4. Execute the five Windows jobs and six Docker Linux jobs sequentially.
5. Require all eleven actual passing receipts for that same head through the
   strict shared validator before publishing successful coverage.

Missing, dry-run, skipped, failed, timed-out or different-head jobs do not
establish complete CI. Preserve real test-level platform skips in their receipts.
Preparation and a successful source-bundle check are not an executed CI pass.

The controller's private runbook contains the reviewed harness location and
dispatch commands. It uses short owned Windows scratch paths, an exclusive
repository lock and immutable inputs. Do not run the Windows worker directly.

## Protect development resources

The reviewed controller bounds the whole Windows worker process tree before its
commands execute. Docker Linux jobs have a 4 GiB memory limit, two CPU cores and
a bounded PID allowance. Only one workflow worker runs at a time, with fresh
memory admission before each gate and owned-resource cleanup after execution.
Keep actual bounds and resource refusals in the receipts; a refusal is incomplete
infrastructure execution, not a passed test. Do not stop unrelated apps or reclaim
their caches to create CI headroom.

## GitHub evidence and merge

Publish actual local results under `private-ci/local-windows/...` and
`private-ci/local-linux/...`. Label remote cross-checks separately under
`private-ci/modal-linux/...`. Keep source, history, fixtures, logs and credentials
private; do not create a public fork to obtain free hosted minutes.

Leave refused GitHub-hosted Actions conclusions unchanged. External coverage
must respect required checks and approvals. Independently review the final
artifact, confirm readiness and branch policy, then ordinarily merge the exact
reviewed head without administrative bypass. Preserve source branches.

Source CI and a source merge do not activate banking actions, install a worker,
deploy a service or establish operator, provider or customer acceptance. The
existing private release and runtime guards remain in force.
