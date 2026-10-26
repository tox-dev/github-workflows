#!/usr/bin/env bash

retry() {
  local attempt
  for attempt in {1..6}; do
    if "$@"; then return 0; fi
    if ((attempt == 6)); then return 1; fi
    echo "Attempt $attempt of 6 failed, retrying in 2s"
    sleep 2
  done
}
