#!/bin/sh
set -e

mkdir -p /app/generated /app/data
chown -R appuser:appuser /app/generated /app/data

exec gosu appuser "$@"
