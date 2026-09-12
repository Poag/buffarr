#!/bin/sh
# Runs as root so it can fix up ownership of a bind-mounted /config before
# dropping to PUID:PGID (default 99:100, Unraid's nobody:users) to actually
# run the app. No named user/group is created -- see the Dockerfile comment
# on why useradd/groupadd are avoided; setpriv works with plain numeric ids.
set -e

PUID="${PUID:-99}"
PGID="${PGID:-100}"

mkdir -p /config
chown -R "$PUID:$PGID" /config

echo "buffarr: starting as uid=$PUID gid=$PGID" >&2

exec setpriv --reuid="$PUID" --regid="$PGID" --clear-groups "$@"
