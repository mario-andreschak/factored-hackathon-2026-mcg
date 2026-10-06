# Validated snapshot publication

The pipeline completes the immutable snapshot, lineage, quality report and required external aggregate reports before atomically replacing `CURRENT`. The serving pointer identifies the active build. New manifests describe candidate readiness; banking reads and dataset health checks also accept historical immutable `published: true` manifests.

At source `2ed5c363dc6ef8cae12f843ad1a97d271451cf40`, **249 tests and 106 subtests passed**, with no failures, errors or skips. Regression cases exercise blocked external manifest and quality-report destinations, a refused pointer swap, retained prior rows and lineage, successful publication, both consumer formats and explicit unready-manifest rejection. The full Banking MCP suite contributes 100 of those tests.

[Qualification and exact reproduction commands](qualification.json) preserve all nine component hashes and the three unmodified JUnit reports. An independent source review verified those hashes, all 89 protected-source entries and consumer compatibility. It did not rerun or add to the test count.

This is synthetic local qualification. Failed report writes can leave partial external aggregate files while the previous serving snapshot remains intact. Atomic pointer replacement does not establish crash durability or a transaction across filesystems. Historical receipts and preserved contribution pins retain their original sources.
