#!/bin/sh
set -eu

case "${UV_PYTHON:-}" in
    *t) export PYTHON_GIL=0 ;;
esac

exec "$@"
