Add `exclude-newer` and `exclude-newer-package` inputs to every Action and reusable workflow that installs its own
tools. `exclude-newer` defaults to `7 days`; `exclude-newer-package` takes newline-separated `name=date` overrides for
an emergency.
