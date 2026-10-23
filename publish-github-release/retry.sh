#!/usr/bin/env bash

retry() {
  local attempt
  for attempt in {1..6}; do
    if "$@"; then return 0; fi
    if ((attempt == 6)); then return 1; fi
    sleep 2
  done
}
