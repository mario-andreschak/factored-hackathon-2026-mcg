# Runtime policy inside the existing FLUJO worker

The optional banking adapter rereads its policy at every authority check. On
Docker Desktop, the Windows staging mount measured 642 ms for 1,000 reads of the
1,541-byte policy; a same-size native Linux file measured 9 ms. This microbenchmark
measures file access, not whole-chat capacity.

## Install

Keep the private host policy mounted read-only at `/run/banking/policy.json` as
**staging**. Configure the existing worker with:

```text
FLUJO_BANKING_CONFIG=/run/banking-runtime/policy.json
```

After creating/recreating that worker, provision the approved policy before
restarting the Slack gateway or admitting customer requests:

```text
docker exec --user 0 EXISTING_WORKER node /opt/banking-mcp/scripts/provision_banking_runtime_policy.mjs APPROVED_POLICY_SHA256
```

Use the SHA-256 of the exact policy already validated and approved for this
deployment. The helper prints only a digest and permission receipt. It copies no
keys into the image and starts no container, service or MCP process.

If worker initialization started before provisioning, restart that same container
after the receipt, then wait for its health check to pass. Missing policy can also
deny the worker's initial control requests. Restarting preserves the provisioned
file; keep the gateway stopped throughout this installation.

The live directory is root-owned, group 1000, mode `0750`; the live policy is
root-owned, group 1000, mode `0440`. FLUJO runs as user 1000 without capabilities:
it can read the policy and cannot write or replace it. `/run` must also remain
root-owned and unwritable by that user. The helper rejects unsuitable paths.

## Updates and restarts

The native file is the **active authority**. Editing staging alone does not change
active policy. Run the root helper with the newly approved digest to publish it.
It uses an exclusive temporary file, file sync, atomic rename and directory sync.
Current checks still read, parse and compare policy on every call; there is no
policy cache or reduced checking interval.

Emergency key removal can be published immediately through this same atomic
update. It does not wait for active runs to finish. In-flight runs observe policy
changes at their next existing authority check. Session revocation still uses the
ordinary optional revocation action and durable state stores.

The native file survives a Docker **restart**. A container **recreation** loses it
and requires reprovisioning. Missing or invalid active policy fails closed; keep
ingress held until the receipt and normal authorization checks pass. Leave the
catalog, signing-key paths, identity stores and OAuth configuration unchanged.
