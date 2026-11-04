The `required-checks` Action fails unless every job in a `needs` context succeeded, and it accepts named jobs that may be
skipped. A gate calls it in place of its own `jq` expression, and the required check name stays with the caller.
