#!/bin/sh
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
/bin/sh "$ROOT/app/bootstrap.sh"
code=$?
if [ "$code" -ne 0 ]; then printf '\nMochi setup needs attention. Press Enter to close.\n';read answer || true; fi
exit "$code"
