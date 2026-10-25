Remove the reviewed cutoff table, the recent cutoff check, the cutoff expiry, and the `verify-cutoff-patch` Action.
Callers own their per-package `uploaded-prior-to` exceptions in `[tool.nab]`; the release lock check honours them, and
nothing checks or expires them.
