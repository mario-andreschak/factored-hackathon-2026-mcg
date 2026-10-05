#!/bin/sh
set -eu

# Recreate the protected native policy on every boot from the approved staging
# mount. The runtime never starts if the bytes differ from the approved digest.
node /opt/banking-mcp/scripts/provision_banking_runtime_policy.mjs "$BANKING_POLICY_SHA256"
exec setpriv --reuid=1000 --regid=1000 --init-groups docker-entrypoint.sh "$@"
