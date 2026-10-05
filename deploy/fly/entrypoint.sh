#!/bin/sh
set -eu

if [ "$(id -u)" != 0 ]; then
  echo '[Savia Fly] Bootstrap requires root before dropping runtime privileges.' >&2
  exit 1
fi
if [ -L /data ] || [ ! -d /data ]; then
  echo '[Savia Fly] The persistent data mount must be a real directory.' >&2
  exit 1
fi

trap 'exit 143' TERM
trap 'exit 130' INT
echo '[Savia Fly] Waiting for the protected configuration migration.'
elapsed=0
while [ ! -f /data/.migration-complete.json ]; do
  if [ "$elapsed" -ge 900 ]; then
    echo '[Savia Fly] Timed out waiting for the configuration migration.' >&2
    exit 1
  fi
  sleep 1
  elapsed=$((elapsed + 1))
done

node /opt/savia/fly/runtime.mjs --bootstrap
trap - TERM INT
exec gosu node:node "$@"
