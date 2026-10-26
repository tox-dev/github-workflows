#!/usr/bin/env bash

plural() {
  if (($1 == 1)); then
    printf '%s %s' "$1" "$2"
  else
    printf '%s %s' "$1" "${3:-${2}s}"
  fi
}
