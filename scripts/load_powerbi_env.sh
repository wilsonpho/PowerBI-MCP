#!/bin/sh

# Loads POWERBI_ACCESS_TOKEN from .env if present, then exports it.
set -a

if [ -f ".env" ]; then
  # shellcheck disable=SC1091
  . ".env"
fi

set +a

if [ -z "${POWERBI_ACCESS_TOKEN}" ]; then
  echo "POWERBI_ACCESS_TOKEN is not set. Export it or create a .env file."
  exit 1
fi

echo "POWERBI_ACCESS_TOKEN loaded."
