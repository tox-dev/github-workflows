The shared workflows lock every action to a commit in `.github/workflows/actions.lock`, which also applies to callers
without a lockfile, and the new `verify-actions-lock.yaml` fails when a workflow uses an action the lockfile does not
cover.
