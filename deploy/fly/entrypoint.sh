#!/bin/sh
set -eu
[ "$(id -u)" = 0 ] || { echo 'Joined bootstrap requires root.' >&2; exit 1; }
[ -d /data ] && [ ! -L /data ] || { echo 'A real persistent volume is required.' >&2; exit 1; }
node /opt/savia/fly/runtime.mjs --bootstrap
exec node /opt/savia/fly/runtime.mjs
